# IpMan.cmake -- drive the XSA -> manifest -> driver pipeline from CMake.
#
#   include(IpMan)
#   ipman_configure(
#     XSA      ${CMAKE_SOURCE_DIR}/hw/design_1.xsa
#     DB       ${CMAKE_SOURCE_DIR}/db/ip-drivers.json   # shared database
#              ${CMAKE_SOURCE_DIR}/db/project-overrides.json  # optional overlay
#     STRICT                       # fail configure if a custom IP has no driver
#     DEFINES  CORP_GIT=https://git.acme.com
#   )
#   target_link_libraries(app PRIVATE ipman::drivers)
#
# Everything happens at configure time: the XSA is parsed, each custom IP is
# looked up in the driver database, the driver sources are fetched or added,
# and a generated header (ipman_ips.h) is put on the include path.
#
# DB takes one or more files: the shared database first, then project overlays
# that add or override entries.  ${PROJECT_ROOT} in a database URI expands to
# CMAKE_SOURCE_DIR, which is how an in-project driver directory is referenced.
#
# Re-running configure is automatic when the XSA or any database changes.
#
# Outputs set in the caller's scope:
#   IPMAN_MANIFEST         path to ip-manifest.json
#   IPMAN_LOCK             path to ip-drivers.lock.json
#   IPMAN_GENERATED_DIR    directory holding the generated header
#   IPMAN_DRIVER_TARGETS   list of driver targets that were added
#   IPMAN_DB_VERSION       version of the driver database that was used

include_guard(GLOBAL)

set(IPMAN_MODULE_DIR "${CMAKE_CURRENT_LIST_DIR}" CACHE INTERNAL "")
set(IPMAN_TOOLS_DIR "${CMAKE_CURRENT_LIST_DIR}/../tools" CACHE PATH
    "Directory containing the ipman Python package")

find_package(Python3 3.9 COMPONENTS Interpreter REQUIRED)

# ipman_run(<output var> <args...>) -- invoke the ipman CLI, fail loudly.
function(ipman_run out_var)
  execute_process(
    COMMAND ${CMAKE_COMMAND} -E env "PYTHONPATH=${IPMAN_TOOLS_DIR}"
            "${Python3_EXECUTABLE}" -m ipman ${ARGN}
    RESULT_VARIABLE _rc
    OUTPUT_VARIABLE _out
    ERROR_VARIABLE _err
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_STRIP_TRAILING_WHITESPACE)
  if(NOT _rc EQUAL 0)
    message(FATAL_ERROR "ipman ${ARGN} failed (exit ${_rc}):\n${_err}\n${_out}")
  endif()
  if(_err)
    message(STATUS "${_err}")
  endif()
  set(${out_var} "${_out}" PARENT_SCOPE)
endfunction()

# ipman_fetch_db(...) -- pull a pinned database version from Artifactory.
#   ipman_fetch_db(URL https://acme.jfrog.io/artifactory REPO fpga-generic
#                  DB_VERSION 1.4.0 OUTPUT ${CMAKE_BINARY_DIR}/ip-drivers.json
#                  TOKEN env:ARTIFACTORY_TOKEN)
function(ipman_fetch_db)
  cmake_parse_arguments(ARG "" "URL;REPO;PREFIX;DB_VERSION;OUTPUT;TOKEN" "" ${ARGN})
  foreach(required URL REPO OUTPUT)
    if(NOT ARG_${required})
      message(FATAL_ERROR "ipman_fetch_db: ${required} is required")
    endif()
  endforeach()
  if(NOT ARG_DB_VERSION)
    set(ARG_DB_VERSION "latest")
  endif()
  set(_args db fetch --url "${ARG_URL}" --repo "${ARG_REPO}"
            --db-version "${ARG_DB_VERSION}" -o "${ARG_OUTPUT}")
  if(ARG_PREFIX)
    list(APPEND _args --prefix "${ARG_PREFIX}")
  endif()
  if(ARG_TOKEN)
    list(APPEND _args --token "${ARG_TOKEN}")
  endif()
  # 'latest' is a moving target, so always re-fetch it; a pinned version is
  # immutable and can be cached across configures.
  if(ARG_DB_VERSION STREQUAL "latest" OR NOT EXISTS "${ARG_OUTPUT}")
    ipman_run(_out ${_args})
    message(STATUS "${_out}")
  endif()
  set(IPMAN_DB "${ARG_OUTPUT}" PARENT_SCOPE)
endfunction()

function(ipman_configure)
  cmake_parse_arguments(ARG "STRICT;INCLUDE_VENDOR"
                            "XSA;OUT_DIR;HEADER_NAME" "DB;DEFINES" ${ARGN})

  if(NOT ARG_XSA)
    message(FATAL_ERROR "ipman_configure: XSA is required")
  endif()
  if(NOT EXISTS "${ARG_XSA}")
    message(FATAL_ERROR "ipman_configure: XSA not found: ${ARG_XSA}")
  endif()
  if(NOT ARG_DB)
    message(FATAL_ERROR "ipman_configure: DB is required")
  endif()
  foreach(database IN LISTS ARG_DB)
    if(NOT EXISTS "${database}")
      message(FATAL_ERROR "ipman_configure: driver database not found: ${database}")
    endif()
  endforeach()
  if(NOT ARG_OUT_DIR)
    set(ARG_OUT_DIR "${CMAKE_BINARY_DIR}/ipman")
  endif()
  if(NOT ARG_HEADER_NAME)
    set(ARG_HEADER_NAME "ipman_ips.h")
  endif()

  set(_args generate --xsa "${ARG_XSA}" --out-dir "${ARG_OUT_DIR}"
            --header-name "${ARG_HEADER_NAME}"
            --project-root "${CMAKE_SOURCE_DIR}")
  foreach(database IN LISTS ARG_DB)
    list(APPEND _args --db "${database}")
  endforeach()
  if(ARG_STRICT)
    list(APPEND _args --strict)
  endif()
  if(ARG_INCLUDE_VENDOR)
    list(APPEND _args --include-vendor)
  endif()
  foreach(define IN LISTS ARG_DEFINES)
    list(APPEND _args -D "${define}")
  endforeach()

  message(STATUS "ipman: parsing ${ARG_XSA}")
  ipman_run(_out ${_args})
  foreach(line IN LISTS _out)
    message(STATUS "${line}")
  endforeach()

  # Reconfigure when the hardware or the driver database changes.
  set_property(DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" APPEND
               PROPERTY CMAKE_CONFIGURE_DEPENDS "${ARG_XSA}" ${ARG_DB})

  include("${ARG_OUT_DIR}/ip_drivers.cmake")

  set(IPMAN_MANIFEST      "${ARG_OUT_DIR}/ip-manifest.json"      PARENT_SCOPE)
  set(IPMAN_LOCK          "${ARG_OUT_DIR}/ip-drivers.lock.json"  PARENT_SCOPE)
  set(IPMAN_GENERATED_DIR "${ARG_OUT_DIR}"                       PARENT_SCOPE)
  set(IPMAN_DRIVER_TARGETS "${IPMAN_DRIVER_TARGETS}"             PARENT_SCOPE)
  set(IPMAN_DB_VERSION    "${IPMAN_DB_VERSION}"                  PARENT_SCOPE)
endfunction()
