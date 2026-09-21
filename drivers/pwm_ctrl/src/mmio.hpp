// Internal register access for the pwm_ctrl driver package.
//
// Both revisions of the register map share this, which matters in simulation:
// the probe reads the ID register through one map type before it knows which
// revision is present, so every map in the package must see the same backing
// store.
#pragma once

#include <cstddef>
#include <cstdint>

namespace acme {
namespace detail {

std::uint32_t read_word(std::uintptr_t base, std::size_t offset);
void write_word(std::uintptr_t base, std::size_t offset, std::uint32_t value);

}  // namespace detail
}  // namespace acme
