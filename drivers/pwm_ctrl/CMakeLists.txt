# Driver package for acme.com:user:pwm_ctrl (hardware 1.x).
#
# This directory is an ipman driver package: it is added by the generated
# ip_drivers.cmake, which sets IPMAN_DRIVER_TARGET / _IP_VERSION / _INSTANCES
# beforehand.  It also configures standalone, which is what its own CI does.
cmake_minimum_required(VERSION 3.20)
project(ipdrv_pwm_ctrl VERSION 1.4.0 LANGUAGES CXX)

if(DEFINED IPMAN_DRIVER_TARGET)
  set(_target "${IPMAN_DRIVER_TARGET}")
else()
  set(_target ipdrv_pwm_ctrl)
endif()

option(IPDRV_SIMULATION "Back the register block with memory instead of MMIO" ON)

add_library(${_target} STATIC src/pwm_ctrl.cpp)
add_library(acme::pwm_ctrl ALIAS ${_target})

target_include_directories(${_target} PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(${_target} PUBLIC cxx_std_17)

# The hardware version ipman matched is handed to the driver so it can assert
# against the register map it was written for.
target_compile_definitions(${_target} PRIVATE
  PWM_CTRL_DRIVER_VERSION="${PROJECT_VERSION}"
  PWM_CTRL_IP_VERSION="$<IF:$<BOOL:${IPMAN_DRIVER_IP_VERSION}>,${IPMAN_DRIVER_IP_VERSION},unknown>"
  $<$<BOOL:${IPDRV_SIMULATION}>:IPDRV_SIMULATION=1>)

message(STATUS "  pwm_ctrl driver ${PROJECT_VERSION} -> ${_target} "
               "(IP ${IPMAN_DRIVER_IP_VERSION}, instances: ${IPMAN_DRIVER_INSTANCES})")
