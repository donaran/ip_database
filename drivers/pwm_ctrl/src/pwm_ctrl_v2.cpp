#include "pwm_ctrl_v2.hpp"

#include <cstddef>
#include <stdexcept>
#include <type_traits>

#include "mmio.hpp"
#include "peakrdl_compat.hpp"  // must precede the generated header on MSVC

#include "pwm_ctrl_v2.h"  // generated: peakrdl c-header -t pwm_ctrl_v2

namespace acme {
namespace {

constexpr std::size_t kCtrl = offsetof(pwm_ctrl_v2_t, CTRL);
constexpr std::size_t kDuty0 = offsetof(pwm_ctrl_v2_t, DUTY);
constexpr std::size_t kPhase0 = offsetof(pwm_ctrl_v2_t, PHASE);
constexpr std::size_t kDutyStride = sizeof(pwm_ctrl_v2__DUTY_t);
constexpr std::size_t kPhaseStride = sizeof(pwm_ctrl_v2__PHASE_t);

constexpr std::uint32_t kEnableBit = PWM_CTRL_V2__CTRL__ENABLE_bm;
constexpr std::uint32_t kInvertBit = PWM_CTRL_V2__CTRL__INVERT_bm;
constexpr std::uint32_t kDutyMask = PWM_CTRL_V2__DUTY__VALUE_bm;
constexpr std::uint32_t kPhaseMask = PWM_CTRL_V2__PHASE__VALUE_bm;

static_assert(PwmCtrlV2::kIdOffset == offsetof(pwm_ctrl_v2_t, ID),
              "ID register moved in the register description");
static_assert(PwmCtrlV2::kMagic == PWM_CTRL_V2__ID__MAGIC_reset,
              "ID magic disagrees with the register description");
static_assert(PwmCtrlV2::kChannels
                  == std::extent<decltype(pwm_ctrl_v2_t::DUTY)>::value,
              "channel count disagrees with the register description");

// The reason 2.x is a major bump: the duty field is wider here than in 1.x, so
// 1.x software writing this block would program a different field.
static_assert(PWM_CTRL_V2__DUTY__VALUE_bw == 16,
              "2.x duty width changed; revisit the revision policy");

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
    write(kDuty0 + kDutyStride * channel, per_mille & kDutyMask);
}

std::uint16_t PwmCtrlV2::duty(std::size_t channel) const {
    if (channel >= kChannels) throw std::out_of_range("pwm_ctrl: bad channel");
    return static_cast<std::uint16_t>(
        read(kDuty0 + kDutyStride * channel) & kDutyMask);
}

void PwmCtrlV2::set_phase(std::size_t channel, std::uint16_t per_mille) {
    if (channel >= kChannels) throw std::out_of_range("pwm_ctrl: bad channel");
    if (per_mille > kMaxDuty) per_mille = kMaxDuty;
    write(kPhase0 + kPhaseStride * channel, per_mille & kPhaseMask);
}

std::uint16_t PwmCtrlV2::phase(std::size_t channel) const {
    if (channel >= kChannels) throw std::out_of_range("pwm_ctrl: bad channel");
    return static_cast<std::uint16_t>(
        read(kPhase0 + kPhaseStride * channel) & kPhaseMask);
}

std::uint8_t PwmCtrlV2::major() const {
    return static_cast<std::uint8_t>(
        (read(kIdOffset) & PWM_CTRL_V2__ID__MAJOR_bm) >> PWM_CTRL_V2__ID__MAJOR_bp);
}

std::uint8_t PwmCtrlV2::minor() const {
    return static_cast<std::uint8_t>(
        (read(kIdOffset) & PWM_CTRL_V2__ID__MINOR_bm) >> PWM_CTRL_V2__ID__MINOR_bp);
}

}  // namespace acme
