cmake_minimum_required(VERSION 3.24)
project(hello_fpga VERSION 0.1.0 LANGUAGES CXX)

# ---------------------------------------------------------------------------
# ipman: parse the XSA, resolve every custom IP to a driver, add the drivers.
# ---------------------------------------------------------------------------
list(APPEND CMAKE_MODULE_PATH "${CMAKE_SOURCE_DIR}/cmake")
include(IpMan)

set(HELLO_XSA "${CMAKE_SOURCE_DIR}/sample/design_1.xsa"
    CACHE FILEPATH "Hardware handoff exported from Vivado")
set(HELLO_IP_DB "${CMAKE_SOURCE_DIR}/db/ip-drivers.json"
    CACHE FILEPATH "Shared driver database (local copy, or fetched from Artifactory)")
set(HELLO_IP_DB_OVERLAY "${CMAKE_SOURCE_DIR}/db/project-overrides.json"
    CACHE FILEPATH "Project-local overlay: drivers still developed in this tree")

# Pin a published database version instead of the checked-in copy with:
#   cmake -DHELLO_IP_DB_VERSION=1.4.0 ...
set(HELLO_IP_DB_VERSION "" CACHE STRING "Artifactory database version to pin")
set(HELLO_ARTIFACTORY_URL "" CACHE STRING "Artifactory base URL")
set(HELLO_ARTIFACTORY_REPO "fpga-generic" CACHE STRING "Artifactory generic repo")

if(HELLO_ARTIFACTORY_URL AND HELLO_IP_DB_VERSION)
  ipman_fetch_db(
    URL        "${HELLO_ARTIFACTORY_URL}"
    REPO       "${HELLO_ARTIFACTORY_REPO}"
    DB_VERSION "${HELLO_IP_DB_VERSION}"
    OUTPUT     "${CMAKE_BINARY_DIR}/ip-drivers.json"
    TOKEN      "env:ARTIFACTORY_TOKEN")
  set(HELLO_IP_DB "${IPMAN_DB}")
endif()

# The demo resolves drivers out of sample/_demo, which sample/bootstrap_demo.py
# populates.  A real project would point these at a corporate git host and an
# Artifactory generic repo instead -- the database URIs are the only thing that
# changes.
ipman_configure(
  XSA     "${HELLO_XSA}"
  DB      "${HELLO_IP_DB}" "${HELLO_IP_DB_OVERLAY}"
  DEFINES "DEMO_GIT=${CMAKE_SOURCE_DIR}/sample/_demo/repos"
          "DEMO_ARCHIVES=${CMAKE_SOURCE_DIR}/sample/_demo/archives"
)

message(STATUS "ipman: driver database v${IPMAN_DB_VERSION}, "
               "targets: ${IPMAN_DRIVER_TARGETS}")

# ---------------------------------------------------------------------------
# The application.  It links one target; ipman decided what is behind it.
# ---------------------------------------------------------------------------
add_executable(hello_fpga src/main.cpp)
target_compile_features(hello_fpga PRIVATE cxx_std_17)
target_link_libraries(hello_fpga PRIVATE ipman::drivers)

if(MSVC)
  target_compile_options(hello_fpga PRIVATE /W4)
else()
  target_compile_options(hello_fpga PRIVATE -Wall -Wextra)
endif()

enable_testing()
add_test(NAME hello_fpga_runs COMMAND hello_fpga)
add_test(NAME ipman_unit_tests
         COMMAND "${Python3_EXECUTABLE}" -m unittest discover -s "${CMAKE_SOURCE_DIR}/tests")
