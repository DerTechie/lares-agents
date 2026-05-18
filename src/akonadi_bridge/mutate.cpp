// SPDX-License-Identifier: MIT
// lares-akonadi-mutate
//
// Long-running helper: reads one JSON request per line on stdin and
// writes one JSON response per line on stdout. Two ops:
//   - fetch:    {"id":"…","op":"fetch","item_id":N}
//               -> {"id":"…","ok":true,"item_id":N,
//                   "headers":{…},"body_text":"…","tags":[…]}
//   - set_tags: {"id":"…","op":"set_tags","item_id":N,"tags":[…]}
//               -> {"id":"…","ok":true,"item_id":N,"tags":[…]}
//
// Tags in the `lares-` namespace are auto-created if missing; non-lares
// tags on the item are preserved across set_tags calls.

#include <QByteArray>
#include <QCommandLineParser>
#include <QCoreApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSocketNotifier>
#include <QString>
#include <QTextDocumentFragment>

#include <Akonadi/Item>
#include <Akonadi/ItemFetchJob>
#include <Akonadi/ItemFetchScope>
#include <Akonadi/ItemModifyJob>
#include <Akonadi/ServerManager>
#include <Akonadi/Tag>
#include <Akonadi/TagCreateJob>

#include <KMime/Message>

#include <iostream>
#include <memory>

namespace
{

constexpr const char *LARES_PREFIX = "lares-";

int g_maxBodyBytes = 8192;

void writeResponse(const QJsonObject &obj)
{
    const auto bytes = QJsonDocument(obj).toJson(QJsonDocument::Compact);
    std::cout << bytes.constData() << '\n';
    std::cout.flush();
}

void writeError(const QString &id, const QString &message, const QString &code)
{
    QJsonObject obj;
    obj.insert("id", id);
    obj.insert("ok", false);
    obj.insert("error", message);
    obj.insert("code", code);
    writeResponse(obj);
}

QString headerOrEmpty(const KMime::Headers::Base *hdr)
{
    return hdr ? hdr->asUnicodeString() : QString();
}

bool ensureAkonadiOnline(const QString &id)
{
    if (Akonadi::ServerManager::state() != Akonadi::ServerManager::Running) {
        writeError(id, QStringLiteral("Akonadi server is not running"),
                   QStringLiteral("akonadi_offline"));
        return false;
    }
    return true;
}

QString extractBody(const std::shared_ptr<KMime::Message> &msg)
{
    auto *plain = msg->mainBodyPart("text/plain");
    if (plain) {
        return plain->decodedText(KMime::Content::NoTrim);
    }
    auto *html = msg->mainBodyPart("text/html");
    if (html) {
        const QString rawHtml = html->decodedText(KMime::Content::NoTrim);
        return QTextDocumentFragment::fromHtml(rawHtml).toPlainText();
    }
    return QString();
}

void handleFetch(const QString &id, qint64 itemId)
{
    if (!ensureAkonadiOnline(id)) {
        return;
    }
    Akonadi::Item item(itemId);
    auto *job = new Akonadi::ItemFetchJob(item);
    job->fetchScope().fetchFullPayload(true);
    job->fetchScope().fetchAllAttributes();
    job->fetchScope().setFetchTags(true);

    QObject::connect(job, &Akonadi::ItemFetchJob::result, [id, itemId](KJob *kjob) {
        auto *fjob = static_cast<Akonadi::ItemFetchJob *>(kjob);
        if (fjob->error() || fjob->items().isEmpty()) {
            writeError(id, fjob->errorString().isEmpty() ? QStringLiteral("not found")
                                                          : fjob->errorString(),
                       QStringLiteral("not_found"));
            return;
        }
        const auto fetched = fjob->items().constFirst();
        QJsonObject resp;
        resp.insert("id", id);
        resp.insert("ok", true);
        resp.insert("item_id", itemId);

        QJsonObject headers;
        if (fetched.hasPayload<std::shared_ptr<KMime::Message>>()) {
            auto msg = fetched.payload<std::shared_ptr<KMime::Message>>();
            headers.insert("From", headerOrEmpty(msg->from()));
            headers.insert("To", headerOrEmpty(msg->to()));
            headers.insert("Subject", headerOrEmpty(msg->subject()));
            auto *listId = msg->headerByType("List-Id");
            headers.insert("List-Id", listId ? listId->asUnicodeString() : QString());
            headers.insert("Date", headerOrEmpty(msg->date()));

            QString body = extractBody(msg);
            const QByteArray utf8 = body.toUtf8();
            if (utf8.size() > g_maxBodyBytes) {
                QByteArray trimmed = utf8.left(g_maxBodyBytes);
                while (!trimmed.isEmpty()
                       && (static_cast<unsigned char>(trimmed.back()) & 0xC0) == 0x80) {
                    trimmed.chop(1);
                }
                if (!trimmed.isEmpty()) {
                    const auto last = static_cast<unsigned char>(trimmed.back());
                    if ((last & 0xE0) == 0xC0 || (last & 0xF0) == 0xE0 || (last & 0xF8) == 0xF0) {
                        trimmed.chop(1);
                    }
                }
                body = QString::fromUtf8(trimmed);
            }
            resp.insert("body_text", body);
        } else {
            resp.insert("body_text", QString());
        }
        resp.insert("headers", headers);

        QJsonArray tagsArr;
        for (const auto &tag : fetched.tags()) {
            tagsArr.append(QString::fromUtf8(tag.gid()));
        }
        resp.insert("tags", tagsArr);

        writeResponse(resp);
    });
}

void applyTagsAndModify(const QString &id, qint64 itemId, Akonadi::Item fetched,
                        const Akonadi::Tag::List &finalTags,
                        const QStringList &requestedTagNames)
{
    fetched.setTags(finalTags);
    auto *modJob = new Akonadi::ItemModifyJob(fetched);
    modJob->disableRevisionCheck();
    QObject::connect(modJob, &KJob::result,
        [id, itemId, requestedTagNames](KJob *mkjob) {
        if (mkjob->error()) {
            writeError(id, mkjob->errorString(), QStringLiteral("internal"));
            return;
        }
        QJsonObject resp;
        resp.insert("id", id);
        resp.insert("ok", true);
        resp.insert("item_id", itemId);
        QJsonArray arr;
        for (const auto &n : requestedTagNames) {
            arr.append(n);
        }
        resp.insert("tags", arr);
        writeResponse(resp);
    });
}

void handleSetTags(const QString &id, qint64 itemId, const QStringList &requestedTagNames)
{
    if (!ensureAkonadiOnline(id)) {
        return;
    }
    // First fetch the current item to learn its existing tags so we can
    // preserve non-lares ones, then replace the lares-* subset.
    Akonadi::Item item(itemId);
    auto *fetchJob = new Akonadi::ItemFetchJob(item);
    fetchJob->fetchScope().setFetchTags(true);

    QObject::connect(fetchJob, &Akonadi::ItemFetchJob::result,
        [id, itemId, requestedTagNames](KJob *kjob) {
        auto *fjob = static_cast<Akonadi::ItemFetchJob *>(kjob);
        if (fjob->error() || fjob->items().isEmpty()) {
            writeError(id, QStringLiteral("not found"), QStringLiteral("not_found"));
            return;
        }
        Akonadi::Item fetched = fjob->items().constFirst();
        Akonadi::Tag::List preserved;
        for (const auto &tag : fetched.tags()) {
            const QByteArray gid = tag.gid();
            if (!gid.startsWith(LARES_PREFIX)) {
                preserved.append(tag);
            }
        }

        if (requestedTagNames.isEmpty()) {
            applyTagsAndModify(id, itemId, fetched, preserved, requestedTagNames);
            return;
        }

        auto counter = std::make_shared<int>(requestedTagNames.size());
        auto accumulated = std::make_shared<Akonadi::Tag::List>(preserved);
        for (const auto &name : requestedTagNames) {
            Akonadi::Tag candidate;
            candidate.setName(name);
            candidate.setGid(name.toUtf8());
            auto *tcj = new Akonadi::TagCreateJob(candidate);
            tcj->setMergeIfExisting(true);
            QObject::connect(tcj, &KJob::result,
                [id, itemId, fetched, accumulated, counter, requestedTagNames](KJob *kj) mutable {
                auto *createJob = static_cast<Akonadi::TagCreateJob *>(kj);
                if (*counter < 0) {
                    return;
                }
                if (createJob->error()) {
                    writeError(id, createJob->errorString(), QStringLiteral("internal"));
                    *counter = -1;
                    return;
                }
                accumulated->append(createJob->tag());
                --*counter;
                if (*counter == 0) {
                    applyTagsAndModify(id, itemId, fetched, *accumulated, requestedTagNames);
                }
            });
        }
    });
}

void dispatch(const QByteArray &line)
{
    QJsonParseError err;
    const auto doc = QJsonDocument::fromJson(line, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) {
        writeError(QStringLiteral("?"), QStringLiteral("invalid JSON"),
                   QStringLiteral("bad_request"));
        return;
    }
    const auto obj = doc.object();
    const QString id = obj.value(QStringLiteral("id")).toString();
    const QString op = obj.value(QStringLiteral("op")).toString();
    const qint64 itemId = obj.value(QStringLiteral("item_id")).toInteger();
    if (op == QStringLiteral("fetch")) {
        handleFetch(id, itemId);
    } else if (op == QStringLiteral("set_tags")) {
        QStringList tagNames;
        for (const auto &v : obj.value(QStringLiteral("tags")).toArray()) {
            tagNames << v.toString();
        }
        handleSetTags(id, itemId, tagNames);
    } else {
        writeError(id, QStringLiteral("unknown op: ") + op, QStringLiteral("bad_request"));
    }
}

} // namespace

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QCoreApplication::setApplicationName(QStringLiteral("lares-akonadi-mutate"));

    QCommandLineParser parser;
    parser.addHelpOption();
    QCommandLineOption maxBodyOpt(QStringLiteral("max-body-bytes"),
        QStringLiteral("Truncate message bodies to N bytes."),
        QStringLiteral("n"), QStringLiteral("8192"));
    parser.addOption(maxBodyOpt);
    parser.process(app);
    g_maxBodyBytes = parser.value(maxBodyOpt).toInt();
    if (g_maxBodyBytes <= 0) {
        g_maxBodyBytes = 8192;
    }

    // Read stdin line-by-line on the event loop using QSocketNotifier on FD 0.
    auto *notifier = new QSocketNotifier(fileno(stdin), QSocketNotifier::Read, &app);
    QObject::connect(notifier, &QSocketNotifier::activated, [notifier](QSocketDescriptor) {
        std::string line;
        if (!std::getline(std::cin, line)) {
            notifier->setEnabled(false);
            QCoreApplication::quit();
            return;
        }
        dispatch(QByteArray::fromStdString(line));
    });

    return app.exec();
}
