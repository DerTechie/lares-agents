# SPDX-License-Identifier: MIT

# extra-cmake-modules ships helper modules (ECMMarkAsTest, ECMGenerateExportHeader,
# KDEInstallDirs, …) that KPim6Akonadi's installed CMake config transitively
# `include()`s. Loading ECM up front and pushing its module path onto
# CMAKE_MODULE_PATH is the canonical KF6/KPim6 consumer preamble.
find_package(ECM REQUIRED NO_MODULE)
list(APPEND CMAKE_MODULE_PATH ${ECM_MODULE_PATH})

find_package(Qt6 REQUIRED COMPONENTS Core DBus Gui)
find_package(KPim6Akonadi REQUIRED)
find_package(KPim6Mime REQUIRED)

add_executable(lares-akonadi-notify notify.cpp)
target_link_libraries(lares-akonadi-notify
    PRIVATE
        Qt6::Core
        Qt6::DBus
        KPim6::AkonadiCore
)
target_compile_features(lares-akonadi-notify PRIVATE cxx_std_17)

install(TARGETS lares-akonadi-notify
        RUNTIME DESTINATION lares/_bin)

add_executable(lares-akonadi-mutate mutate.cpp)
target_link_libraries(lares-akonadi-mutate
    PRIVATE
        Qt6::Core
        Qt6::DBus
        Qt6::Gui
        KPim6::AkonadiCore
        KPim6::Mime
)
target_compile_features(lares-akonadi-mutate PRIVATE cxx_std_17)

install(TARGETS lares-akonadi-mutate
        RUNTIME DESTINATION lares/_bin)
