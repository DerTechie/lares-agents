// SPDX-License-Identifier: MIT
// lares-akonadi-notify
//
// Wraps Akonadi::Monitor. Subscribes to itemAdded events for collections
// flagged as inbox (Akonadi::SpecialCollectionAttribute) restricted to
// message/rfc822, and writes one NDJSON line per event to stdout.
//
// Usage: lares-akonadi-notify --mimetype <m> --collection-attr <name>
//                             [--extra-collection NAME ...]

#include <QCommandLineParser>
#include <QCoreApplication>
#include <QDateTime>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTextStream>
#include <iostream>

#include <Akonadi/Collection>
#include <Akonadi/Item>
#include <Akonadi/Monitor>
#include <Akonadi/SpecialCollectionAttribute>

namespace
{

void emitEvent(const Akonadi::Item &item, const Akonadi::Collection &collection)
{
    QJsonObject obj;
    obj.insert("event", "item_added");
    obj.insert("item_id", static_cast<qint64>(item.id()));
    obj.insert("collection_id", static_cast<qint64>(collection.id()));
    obj.insert("remote_id", item.remoteId());
    obj.insert("mimetype", item.mimeType());
    obj.insert("ts", QDateTime::currentDateTimeUtc().toString(Qt::ISODate));

    const auto bytes = QJsonDocument(obj).toJson(QJsonDocument::Compact);
    std::cout << bytes.constData() << '\n';
    std::cout.flush();
}

} // namespace

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QCoreApplication::setApplicationName(QStringLiteral("lares-akonadi-notify"));

    QCommandLineParser parser;
    parser.addHelpOption();
    QCommandLineOption mimeOpt(QStringLiteral("mimetype"),
        QStringLiteral("Akonadi mimetype to monitor."),
        QStringLiteral("mime"), QStringLiteral("message/rfc822"));
    QCommandLineOption attrOpt(QStringLiteral("collection-attr"),
        QStringLiteral("SpecialCollectionAttribute type to include (e.g. inbox)."),
        QStringLiteral("name"), QStringLiteral("inbox"));
    QCommandLineOption extraOpt(QStringLiteral("extra-collection"),
        QStringLiteral("Extra collection name to monitor (repeatable)."),
        QStringLiteral("name"));
    parser.addOption(mimeOpt);
    parser.addOption(attrOpt);
    parser.addOption(extraOpt);
    parser.process(app);

    auto *monitor = new Akonadi::Monitor(&app);
    monitor->setMimeTypeMonitored(parser.value(mimeOpt));
    // Akonadi::Monitor by itself fires for every monitored mimetype across
    // every collection the session can see. Filtering to inbox-like
    // collections happens inside the slot: cheap and avoids depending on
    // SpecialCollectionAttribute being set at startup (it's lazy on first
    // resource sync).
    const QString inboxAttrType = parser.value(attrOpt).toLower();
    const QStringList extraNames = parser.values(extraOpt);

    QObject::connect(monitor, &Akonadi::Monitor::itemAdded,
        [inboxAttrType, extraNames](const Akonadi::Item &item,
                                    const Akonadi::Collection &collection) {
            bool include = false;
            if (extraNames.contains(collection.name())) {
                include = true;
            } else if (collection.hasAttribute<Akonadi::SpecialCollectionAttribute>()) {
                const auto *attr =
                    collection.attribute<Akonadi::SpecialCollectionAttribute>();
                if (attr && attr->collectionType().toLower() == inboxAttrType.toUtf8()) {
                    include = true;
                }
            }
            if (include) {
                emitEvent(item, collection);
            }
        });

    return app.exec();
}
