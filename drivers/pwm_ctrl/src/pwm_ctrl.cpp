#include "pwm_ctrl.hpp"

#include <stdexcept>

#ifdef IPDRV_SIMULATION
#include <array>
#include <map>
#endif

namespace acme {
namespace {

constexpr std::size_t kCtrl = 0x00;
constexpr std::size_t kDuty0 = 0x04;
constexpr std::size_t kIdReg = 0x0C;
constexpr std::uint32_t kEnableBit = 1u;

#ifdef IPDRV_SIMULATION
// Off-target builds (host tests, this demo) get a plain memory model instead
// of touching a physical address that does not exist.
std::array<std::uint32_t, 16>& sim_block(std::uintptr_t base) {
    static std::map<std::uintptr_t, std::array<std::uint32_t, 16>> blocks;
    auto it = blocks.find(base);
    if (it == blocks.end()) {
        it = blocks.emplace(base, std::array<std::uint32_t, 16>{}).first;
        it->second[kIdReg / 4] = 0x50574D01u;  // 'PWM' + version nibble
    }
    return it->second;
}
#endif

}  // namespace

PwmCtrl::PwmCtrl(std::uintptr_t base_addr, std::string instance)
    : base_(base_addr), instance_(std::move(instance)) {}

std::uint32_t PwmCtrl::read(std::size_t offset) const {
#ifdef IPDRV_SIMULATION
    return sim_block(base_)[offset / 4];
#else
    return *reinterpret_cast<volatile std::uint32_t*>(base_ + offset);
#endif
}

void PwmCtrl::write(std::size_t offset, std::uint32_t value) {
#ifdef IPDRV_SIMULATION
    sim_block(base_)[offset / 4] = value;
#else
    *reinterpret_cast<volatile std::uint32_t*>(base_ + offset) = value;
#endif
}

void PwmCtrl::enable(bool on) {
    std::uint32_t ctrl = read(kCtrl);
    write(kCtrl, on ? (ctrl | kEnableBit) : (ctrl & ~kEnableBit));
}

bool PwmCtrl::enabled() const { return (read(kCtrl) & kEnableBit) != 0; }

void PwmCtrl::set_duty(std::size_t channel, std::uint16_t per_mille) {
    if (channel >= kChannels) throw std::out_of_range("pwm_ctrl: bad channel");
    if (per_mille > 1000) per_mille = 1000;
    write(kDuty0 + 4 * channel, per_mille);
}

std::uint16_t PwmCtrl::duty(std::size_t channel) const {
    if (channel >= kChannels) throw std::out_of_range("pwm_ctrl: bad channel");
    return static_cast<std::uint16_t>(read(kDuty0 + 4 * channel) & 0xFFFFu);
}

const char* PwmCtrl::driver_version() {
#ifdef PWM_CTRL_DRIVER_VERSION
    return PWM_CTRL_DRIVER_VERSION;
#else
    return "unknown";
#endif
}

const char* PwmCtrl::built_for_ip_version() {
#ifdef PWM_CTRL_IP_VERSION
    return PWM_CTRL_IP_VERSION;
#else
    return "unknown";
#endif
}

}  // namespace acme
