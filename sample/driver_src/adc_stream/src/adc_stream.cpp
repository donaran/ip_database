#include "adc_stream.hpp"

#ifdef IPDRV_SIMULATION
#include <array>
#include <map>
#endif

namespace acme {
namespace {

constexpr std::size_t kCtrl = 0x00;
constexpr std::size_t kStatus = 0x04;
constexpr std::size_t kFifo = 0x08;
constexpr std::size_t kCount = 0x0C;
constexpr std::uint32_t kStartBit = 1u;
constexpr std::uint32_t kBusyBit = 1u;

#ifdef IPDRV_SIMULATION
struct SimState {
    std::array<std::uint32_t, 8> regs{};
    std::uint32_t next_sample = 0x1000;
};

SimState& sim_state(std::uintptr_t base) {
    static std::map<std::uintptr_t, SimState> blocks;
    return blocks[base];
}
#endif

}  // namespace

AdcStream::AdcStream(std::uintptr_t base_addr, std::string instance)
    : base_(base_addr), instance_(std::move(instance)) {}

std::uint32_t AdcStream::read(std::size_t offset) const {
#ifdef IPDRV_SIMULATION
    SimState& sim = sim_state(base_);
    if (offset == kFifo && (sim.regs[kCtrl / 4] & kStartBit)) {
        // Hand back a ramp so the demo has something to print.
        sim.regs[kCount / 4] += 1;
        return sim.next_sample++;
    }
    return sim.regs[offset / 4];
#else
    return *reinterpret_cast<volatile std::uint32_t*>(base_ + offset);
#endif
}

void AdcStream::write(std::size_t offset, std::uint32_t value) {
#ifdef IPDRV_SIMULATION
    SimState& sim = sim_state(base_);
    sim.regs[offset / 4] = value;
    if (offset == kCtrl) {
        sim.regs[kStatus / 4] = (value & kStartBit) ? kBusyBit : 0u;
        if (value & kStartBit) sim.regs[kCount / 4] = 0;
    }
#else
    *reinterpret_cast<volatile std::uint32_t*>(base_ + offset) = value;
#endif
}

void AdcStream::start(bool continuous) {
    write(kCtrl, kStartBit | (continuous ? 2u : 0u));
}

void AdcStream::stop() { write(kCtrl, 0u); }

bool AdcStream::busy() const { return (read(kStatus) & kBusyBit) != 0; }

std::uint32_t AdcStream::sample_count() const { return read(kCount); }

std::vector<std::uint32_t> AdcStream::read_samples(std::size_t max_samples) {
    std::vector<std::uint32_t> out;
    out.reserve(max_samples);
    for (std::size_t i = 0; i < max_samples && busy(); ++i) {
        out.push_back(read(kFifo));
    }
    return out;
}

const char* AdcStream::driver_version() {
#ifdef ADC_STREAM_DRIVER_VERSION
    return ADC_STREAM_DRIVER_VERSION;
#else
    return "unknown";
#endif
}

}  // namespace acme
