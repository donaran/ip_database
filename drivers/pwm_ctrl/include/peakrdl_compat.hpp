// Makes PeakRDL-cheader output usable on MSVC.
//
// peakrdl c-header emits its address-space overlay as
//
//     typedef struct __attribute__ ((__packed__)) { ... } pwm_ctrl_v1_t;
//
// which is GCC/Clang syntax. On the real target -- arm-none-eabi-gcc,
// aarch64-linux-gnu-gcc -- that is exactly right. MSVC, which is what the host
// build of this repo uses, rejects it outright.
//
// Neutralising __attribute__ is safe *for this register map*: every member is a
// uint32_t, so there is nothing for packing to do, and the generated
// static_assert on the struct size still holds the layout honest. It would not
// be safe for a map with sub-word members, and the static_assert is what would
// catch that.
//
// Include this before any generated header. The driver's own sources do.
#pragma once

#if defined(_MSC_VER) && !defined(__clang__) && !defined(__GNUC__)
#ifndef __attribute__
#define __attribute__(x)
#endif
#endif
