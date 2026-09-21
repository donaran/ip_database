#include "pwm_ctrl_v2.hpp"

#include <stdexcept>

#include "mmio.hpp"

namespace acme {
namespace {

constexpr std::size_t kCtrl = 0x04;
constexpr std::size_t kDuty0 = 0x08;
constexpr std::size_t kPhase0 = 0x10;
constexpr std::uint32_t kEnableBit = 1u;
constexpr std::uint32_t kInvertBit = 2u;
constexpr std::uint32_t kDutyMask = 0xFFFFu;  // widened to 16 bits in 2.x

}  // namespace

std::uint32_t PwmCtrlV2::read_word(std::uintptr_t base, std::size_t offset) {
    return detail::read_word(base, offset);
}

PwmCtrlV2::PwmCtrlV2(std::uintptr_t base) : base_(base) {}

std::uint32_t PwmCtrlV2::read(std::size_t offset) const {
    return detail::read_word(base_, offset);
}

void PwmCtrlV2::write(std::size_t offset, std::uint32_t value) {
    detail::write_word(base_, offset, value);
}

void PwmCtrlV2::enable(bool on) {
    const std::uint32_t ctrl = read(kCtrl);
    write(kCtrl, on ? (ctrl | kEnableBit) : (ctrl & ~kEnableBit));
}

bool PwmCtrlV2::enabled() const { return (read(kCtrl) & kEnableBit) != 0; }

void PwmCtrlV2::set_invert(bool on) {
    const std::uint32_t ctrl = read(kCtrl);
    write(kCtrl, on ? (ctrl | kInvertBit) : (ctrl & ~kInvertBit));
}

bool PwmCtrlV2::inverted() const { return (read(kCtrl) & kInvertBit) != 0; }

void PwmCtrlV2::set_duty(std::size_t channel, std::uint16_t per_mille) {
    if (channel >= kChannels) throw std::out_of_range("pwm_ctrl: bad channel");
    if (per_mille > kMaxDuty) per_mille = kMaxDuty;
    write(kDuty0 + 4 * channel, per_mille & kDutyMask);
}

std::uint16_t PwmCtrlV2::duty(std::size_t channel) const {
    if (channel >= kChannels) throw std::out_of_range("pwm_ctrl: bad channel");
    return static_cast<std::uint16_t>(read(kDuty0 + 4 * channel) & kDutyMask);
}

void PwmCtrlV2::set_phase(std::size_t channel, std::uint16_t per_mille) {
    if (channel >= kChannels) throw std::out_of_range("pwm_ctrl: bad channel");
    if (per_mille > kMaxDuty) per_mille = kMaxDuty;
    write(kPhase0 + 4 * channel, per_mille & kDutyMask);
}

std::uint16_t PwmCtrlV2::phase(std::size_t channel) const {
    if (channel >= kChannels) throw std::out_of_range("pwm_ctrl: bad channel");
    return static_cast<std::uint16_t>(read(kPhase0 + 4 * channel) & kDutyMask);
}

std::uint8_t PwmCtrlV2::major() const {
    return static_cast<std::uint8_t>((read(kIdOffset) >> 8) & 0xFFu);
}

std::uint8_t PwmCtrlV2::minor() const {
    return static_cast<std::uint8_t>(read(kIdOffset) & 0xFFu);
}

}  // namespace acme
