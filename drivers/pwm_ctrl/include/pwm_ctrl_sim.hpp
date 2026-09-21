// Simulation-only controls for the pwm_ctrl driver.
//
// Built only when IPDRV_SIMULATION is defined, which is the host build. On a
// cross build for the target these do not exist, so code that calls them will
// fail to compile rather than silently doing nothing.
#pragma once

#include <cstdint>

#ifdef IPDRV_SIMULATION

namespace acme {

// Makes the simulated ID register report a different hardware revision, so the
// runtime register-map dispatch can be exercised without a new bitstream.
void sim_set_ip_version(std::uintptr_t base, std::uint8_t major,
                        std::uint8_t minor);

// Clears the simulated registers, keeping the ID register.
void sim_reset(std::uintptr_t base);

}  // namespace acme

#endif  // IPDRV_SIMULATION
