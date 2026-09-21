# Driver package for acme.com:user:axi_gpio_lite (hardware 1.x).
# Stands in for a driver that lives in its own git repository.
cmake_minimum_required(VERSION 3.20)
project(ipdrv_axi_gpio_lite VERSION 1.0.0 LANGUAGES CXX)

if(DEFINED IPMAN_DRIVER_TARGET)
  set(_target "${IPMAN_DRIVER_TARGET}")
else()
  set(_target ipdrv_axi_gpio_lite)
endif()

option(IPDRV_SIMULATION "Back the register block with memory instead of MMIO" ON)

add_library(${_target} STATIC src/axi_gpio_lite.cpp)
add_library(acme::axi_gpio_lite ALIAS ${_target})

target_include_directories(${_target} PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(${_target} PUBLIC cxx_std_17)
target_compile_definitions(${_target} PRIVATE
  GPIO_LITE_DRIVER_VERSION="${PROJECT_VERSION}"
  $<$<BOOL:${IPDRV_SIMULATION}>:IPDRV_SIMULATION=1>)

message(STATUS "  axi_gpio_lite driver ${PROJECT_VERSION} -> ${_target} "
               "(IP ${IPMAN_DRIVER_IP_VERSION}, instances: ${IPMAN_DRIVER_INSTANCES})")
