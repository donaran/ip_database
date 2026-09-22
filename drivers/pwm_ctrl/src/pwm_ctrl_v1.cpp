#include "pwm_ctrl_v1.hpp"

#include <cstddef>
#include <stdexcept>
#include <type_traits>

#include "mmio.hpp"
#include "peakrdl_compat.hpp"  // must precede the generated header on MSVC

#include "pwm_ctrl_v1.h"  // generated: peakrdl c-header -t pwm_ctrl_v1

namespace acme {
namespace {

// Offsets come from the generated address-space overlay and masks from the
// generated field macros, so both are the register description's rather than
// ours. Editing rdl/pwm_ctrl.rdl moves them; nothing here needs touching.
constexpr std::size_t kCtrl = offsetof(pwm_ctrl_v1_t, CTRL);
constexpr std::size_t kDuty0 = offsetof(pwm_ctrl_v1_t, DUTY);
constexpr std::size_t kDutyStride = sizeof(pwm_ctrl_v1__DUTY_t);

constexpr std::uint32_t kEnableBit = PWM_CTRL_V1__CTRL__ENABLE_bm;
constexpr std::uint32_t kDutyMask = PWM_CTRL_V1__DUTY__VALUE_bm;

// The hand-written class states the ID register contract; the generated map
// states where the register actually is. If the .rdl ever moves it, this stops
// the build rather than producing a driver that probes the wrong word.
static_assert(PwmCtrlV1::kIdOffset == offsetof(pwm_ctrl_v1_t, ID),
              "ID register moved in the register description");
static_assert(PwmCtrlV1::kMagic == PWM_CTRL_V1__ID__MAGIC_reset,
              "ID magic disagrees with the register description");
static_assert(PwmCtrlV1::kChannels
                  == std::extent<decltype(pwm_ctrl_v1_t::DUTY)>::value,
              "channel count disagrees with the register description");

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
    write(kDuty0 + kDutyStride * channel, per_mille & kDutyMask);
}

std::uint16_t PwmCtrlV1::duty(std::size_t channel) const {
    if (channel >= kChannels) throw std::out_of_range("pwm_ctrl: bad channel");
    return static_cast<std::uint16_t>(
        read(kDuty0 + kDutyStride * channel) & kDutyMask);
}

std::uint8_t PwmCtrlV1::major() const {
    return static_cast<std::uint8_t>(
        (read(kIdOffset) & PWM_CTRL_V1__ID__MAJOR_bm) >> PWM_CTRL_V1__ID__MAJOR_bp);
}

std::uint8_t PwmCtrlV1::minor() const {
    return static_cast<std::uint8_t>(
        (read(kIdOffset) & PWM_CTRL_V1__ID__MINOR_bm) >> PWM_CTRL_V1__ID__MINOR_bp);
}

}  // namespace acme
