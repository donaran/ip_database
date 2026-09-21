#include "pwm_ctrl_v1.hpp"

#include <stdexcept>

#include "mmio.hpp"

namespace acme {
namespace {

constexpr std::size_t kCtrl = 0x04;
constexpr std::size_t kDuty0 = 0x08;
constexpr std::uint32_t kEnableBit = 1u;
constexpr std::uint32_t kDutyMask = 0x3FFu;  // 10 bits in 1.x

}  // namespace

std::uint32_t PwmCtrlV1::read_word(std::uintptr_t base, std::size_t offset) {
    return detail::read_word(base, offset);
}

PwmCtrlV1::PwmCtrlV1(std::uintptr_t base) : base_(base) {}

std::uint32_t PwmCtrlV1::read(std::size_t offset) const {
    return detail::read_word(base_, offset);
}

void PwmCtrlV1::write(std::size_t offset, std::uint32_t value) {
    detail::write_word(base_, offset, value);
}

void PwmCtrlV1::enable(bool on) {
    const std::uint32_t ctrl = read(kCtrl);
    write(kCtrl, on ? (ctrl | kEnableBit) : (ctrl & ~kEnableBit));
}

bool PwmCtrlV1::enabled() const { return (read(kCtrl) & kEnableBit) != 0; }

void PwmCtrlV1::set_duty(std::size_t channel, std::uint16_t per_mille) {
    if (channel >= kChannels) throw std::out_of_range("pwm_ctrl: bad channel");
    if (per_mille > kMaxDuty) per_mille = kMaxDuty;
    write(kDuty0 + 4 * channel, per_mille & kDutyMask);
}

std::uint16_t PwmCtrlV1::duty(std::size_t channel) const {
    if (channel >= kChannels) throw std::out_of_range("pwm_ctrl: bad channel");
    return static_cast<std::uint16_t>(read(kDuty0 + 4 * channel) & kDutyMask);
}

std::uint8_t PwmCtrlV1::major() const {
    return static_cast<std::uint8_t>((read(kIdOffset) >> 8) & 0xFFu);
}

std::uint8_t PwmCtrlV1::minor() const {
    return static_cast<std::uint8_t>(read(kIdOffset) & 0xFFu);
}

}  // namespace acme
