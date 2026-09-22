# PeakRdl.cmake -- keep committed PeakRDL output honest.
#
# The generated register headers and RTL are committed, so building a driver
# needs only a C++ toolchain. The risk that buys is drift: someone edits the
# .rdl and forgets to regenerate, or hand-edits a generated file. This adds a
# test that regenerates into a temporary directory and compares.
#
#   include(PeakRdl)
#   peakrdl_check_generated(
#     NAME   pwm_ctrl
#     SCRIPT ${CMAKE_SOURCE_DIR}/drivers/pwm_ctrl/regenerate.py)
#
# PeakRDL is not required. If it is not installed the test is registered as
# skipped rather than failing, because a consumer of a driver has no reason to
# have it:
#
#   pip install peakrdl peakrdl-regblock-vhdl
#
# Point at a specific install with -DPEAKRDL_EXECUTABLE=/path/to/peakrdl, which
# is how a venv or a pinned version gets used.

include_guard(GLOBAL)

find_package(Python3 COMPONENTS Interpreter QUIET)

find_program(PEAKRDL_EXECUTABLE
  NAMES peakrdl
  DOC "PeakRDL command line tool")

if(PEAKRDL_EXECUTABLE)
  execute_process(
    COMMAND "${PEAKRDL_EXECUTABLE}" --version
    OUTPUT_VARIABLE _peakrdl_version
    ERROR_QUIET OUTPUT_STRIP_TRAILING_WHITESPACE)
  message(STATUS "peakrdl: ${PEAKRDL_EXECUTABLE} (${_peakrdl_version})")
else()
  message(STATUS "peakrdl: not found; generated-output checks will skip")
endif()

# peakrdl_check_generated(NAME <label> SCRIPT <regenerate.py>)
#
# Adds a test that runs the package's own regenerate script in --check mode.
# The script owns the exporter flags; this only decides when to run it, so the
# flags cannot drift between CI and whoever regenerates by hand.
function(peakrdl_check_generated)
  cmake_parse_arguments(ARG "" "NAME;SCRIPT" "" ${ARGN})
  foreach(required NAME SCRIPT)
    if(NOT ARG_${required})
      message(FATAL_ERROR "peakrdl_check_generated: ${required} is required")
    endif()
  endforeach()
  if(NOT EXISTS "${ARG_SCRIPT}")
    message(FATAL_ERROR "peakrdl_check_generated: no such script: ${ARG_SCRIPT}")
  endif()

  set(_test "peakrdl_generated_${ARG_NAME}")

  if(NOT PEAKRDL_EXECUTABLE OR NOT Python3_Interpreter_FOUND)
    add_test(NAME ${_test}
             COMMAND ${CMAKE_COMMAND} -E echo
                     "peakrdl not installed; skipping generated-output check")
    set_tests_properties(${_test} PROPERTIES DISABLED TRUE)
    return()
  endif()

  add_test(NAME ${_test}
           COMMAND "${Python3_EXECUTABLE}" "${ARG_SCRIPT}" --check
                   --peakrdl "${PEAKRDL_EXECUTABLE}")
  set_tests_properties(${_test} PROPERTIES LABELS "generated")
endfunction()
