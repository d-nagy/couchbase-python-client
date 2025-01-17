# Copyright (C) 2021 Couchbase, Inc
# All rights reserved.
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

cmake_minimum_required(VERSION 3.17)
project(couchbase_client)
include(FetchContent)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_VERBOSE_MAKEFILE ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if (PYTHON_VERSION_EXACT)
    set(Python_FIND_VIRTUALENV FIRST)
    message("finding python version ${PYTHON_VERSION_EXACT}")

else()
    set(PYTHON_VERSION_EXACT 3.6)
endif()
find_package(Python3 ${PYTHON_VERSION_EXACT} COMPONENTS Interpreter Development)

if(WIN32)
    set(PYCBC_C_MOD_SUFFIX ".pyd")
else()
    set(PYCBC_C_MOD_SUFFIX ".so")
endif()

if (OPENSSL_ROOT_DIR)
    message(STATUS "OPENSSL_ROOT_DIR set to ${OPENSSL_ROOT_DIR}, calling finder...")
    find_package(OpenSSL REQUIRED)
endif()

if(OPENSSL_FOUND)
    message("OpenSSL found, OPENSSL_ROOT_DIR set to ${OPENSSL_ROOT_DIR}")
else()
    if(WIN32)
        if("${CMAKE_SIZEOF_VOID_P}" EQUAL "8")
            MESSAGE("++ 64 bit architecture")
            set(PKGARCH "amd64")
        else()
            MESSAGE("++ 32 bit architecture")
            set(PKGARCH "win32")
        endif()
        if(NOT OPENSSL_VERSION)
            message("No OpenSSL version set...cannot attempt to download.")
        else()
            # default version is currently 1.1.1g (see setup.py)
            FetchContent_Declare(
                openssl
                URL https://github.com/python/cpython-bin-deps/archive/openssl-bin-${OPENSSL_VERSION}.zip
            )
            message("fetching OpenSSL version: ${OPENSSL_VERSION}")
            FetchContent_Populate(openssl)
            message("Downloaded OpenSSL: ${openssl_SOURCE_DIR}/${PKGARCH}")
            set(OPENSSL_ROOT_DIR ${openssl_SOURCE_DIR}/${PKGARCH})
            file(GLOB_RECURSE OPENSSL_DLLS "${OPENSSL_ROOT_DIR}/libcrypto-1_1*.dll"  "${OPENSSL_ROOT_DIR}/libssl-1_1*.dll")
        endif()
    elseif(APPLE)
        # we were not supplied an OPENSSL_ROOT_DIR, so for macos assume brew is how it is installed, if it is...
        find_program(BREW_COMMAND brew)
        if(BREW_COMMAND)
            message(STATUS "brew command: ${BREW_COMMAND}")
            execute_process(COMMAND ${BREW_COMMAND} --prefix openssl@1.1 OUTPUT_VARIABLE BREW_OPENSSL_PREFIX RESULT_VARIABLE BREW_RESULT OUTPUT_STRIP_TRAILING_WHITESPACE)
            message(STATUS "brew result: ${BREW_RESULT}, prefix: ${BREW_OPENSSL_PREFIX}")
            if(BREW_RESULT EQUAL 0)
                set(OPENSSL_ROOT_DIR ${BREW_OPENSSL_PREFIX} CACHE INTERNAL "" FORCE)
                message(STATUS "brew set OPENSSL_ROOT_DIR to ${OPENSSL_ROOT_DIR}, finding OpenSSL...")
            endif()
        endif()
    else()
        message("OpenSSL not found.  OpenSSL >= 1.1.1 required.")
    endif()
endif()

# @TODO:  I think this is only for debug...couchnode did this recently
# Set up some build requirements for Windows.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
if(WIN32)
  add_definitions(/bigobj)
  add_definitions(-D_WIN32_WINNT=0x0601)
endif()

set(COUCHBASE_CXX_CLIENT_PYTHON_WARNINGS ON CACHE INTERNAL "")
set(COUCHBASE_CXX_CLIENT_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(COUCHBASE_CXX_CLIENT_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
#set(COUCHBASE_CXX_CLIENT_POST_LINKED_OPENSSL ON CACHE BOOL "" FORCE)
set(COUCHBASE_CXX_CLIENT_STATIC_STDLIB ON CACHE BOOL "" FORCE)
add_subdirectory(deps/couchbase-cxx-client)

set(COUCHBASE_TXNS_CXX_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(COUCHBASE_TXNS_CXX_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(COUCHBASE_TXNS_CXX_BUILD_DOC OFF CACHE BOOL "" FORCE)
set(COUCHBASE_TXNS_CXX_CLIENT_EXTERNAL ON CACHE BOOL "" FORCE)
add_subdirectory(deps/couchbase-transactions-cxx)

set(TXN_DIR "${PROJECT_SOURCE_DIR}/deps/couchbase-transactions-cxx")
set(CB_CXX_DIR "${PROJECT_SOURCE_DIR}/deps/couchbase-cxx-client")

if(Python3_FOUND)
    message("Python executable: ${Python3_EXECUTABLE}")
    message("Python include dir: ${Python3_INCLUDE_DIRS}")
    message("Python libs: ${Python3_LIBRARIES}")
else()
    message(FATAL_ERROR "Python3 not found.")
endif()

include_directories(SYSTEM ${Python3_INCLUDE_DIRS})
include_directories(BEFORE "${TXN_DIR}/include")
include_directories(BEFORE "${CB_CXX_DIR}/include")
include_directories(BEFORE "${CB_CXX_DIR}/third_party/asio/asio/include")
file(GLOB SOURCE_FILES "src/*.cxx" "src/management/*.cxx" "src/transactions/*.cxx")
add_library(pycbc_core SHARED ${SOURCE_FILES})

if(WIN32)
    target_link_libraries(pycbc_core couchbase_cxx_client transactions_cxx ${Python3_LIBRARIES})
    foreach(DLL IN LISTS OPENSSL_DLLS)
        add_custom_command(
            TARGET pycbc_core POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy ${DLL} "${PROJECT_SOURCE_DIR}/couchbase"
            COMMENT "Copy ${DLL} to ${PROJECT_SOURCE_DIR}/couchbase directory")
    endforeach()
else()
    target_link_libraries(pycbc_core couchbase_cxx_client transactions_cxx)
    if(APPLE)
        target_link_options(pycbc_core PRIVATE -undefined dynamic_lookup)
    endif()
endif()

set_target_properties(pycbc_core
        PROPERTIES
        PREFIX ""
        OUTPUT_NAME pycbc_core
        SUFFIX ${PYCBC_C_MOD_SUFFIX}
        )
