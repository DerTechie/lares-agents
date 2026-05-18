# SPDX-License-Identifier: MIT
cmake_minimum_required(VERSION 3.20)
project(lares LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

# The Akonadi-bridge C++ helpers (lares-akonadi-notify, lares-akonadi-mutate)
# are added once their CMakeLists.txt is in place. Gating keeps the
# Python-only wheel buildable during early bootstrap tasks.
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/src/akonadi_bridge/CMakeLists.txt")
    add_subdirectory(src/akonadi_bridge)
endif()

# Copy the systemd unit into the wheel so importlib.resources can find it.
install(FILES packaging/systemd/lares-kmail.service
        DESTINATION lares/_systemd)
