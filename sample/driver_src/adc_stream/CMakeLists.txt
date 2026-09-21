# Driver package for acme.com:user:adc_stream (hardware 2.x).
# Stands in for a driver shipped as a tarball from an Artifactory generic repo.
cmake_minimum_required(VERSION 3.20)
project(ipdrv_adc_stream VERSION 2.1.0 LANGUAGES CXX)

if(DEFINED IPMAN_DRIVER_TARGET)
  set(_target "${IPMAN_DRIVER_TARGET}")
else()
  set(_target ipdrv_adc_stream)
endif()

option(IPDRV_SIMULATION "Back the register block with memory instead of MMIO" ON)

add_library(${_target} STATIC src/adc_stream.cpp)
add_library(acme::adc_stream ALIAS ${_target})

target_include_directories(${_target} PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(${_target} PUBLIC cxx_std_17)
target_compile_definitions(${_target} PRIVATE
  ADC_STREAM_DRIVER_VERSION="${PROJECT_VERSION}"
  $<$<BOOL:${IPDRV_SIMULATION}>:IPDRV_SIMULATION=1>)

message(STATUS "  adc_stream driver ${PROJECT_VERSION} -> ${_target} "
               "(IP ${IPMAN_DRIVER_IP_VERSION}, instances: ${IPMAN_DRIVER_INSTANCES})")
