// hello_fpga -- a hello world that knows what is in its bitstream.
//
// Nothing here is hand-maintained: ipman_ips.h is generated from the XSA at
// configure time, and the driver headers come from whichever driver packages
// the database resolved for the IP versions actually present in the design.

#include <cstdio>

#include "ipman_ips.h"

#if __has_include("pwm_ctrl.hpp")
#include "pwm_ctrl.hpp"
#define HAVE_PWM_CTRL 1
#endif

#if __has_include("adc_stream.hpp")
#include "adc_stream.hpp"
#define HAVE_ADC_STREAM 1
#endif

#if __has_include("axi_gpio_lite.hpp")
#include "axi_gpio_lite.hpp"
#define HAVE_AXI_GPIO_LITE 1
#endif

namespace {

void print_inventory() {
    std::printf("hello_fpga\n");
    std::printf("  hardware      : %s\n", IPMAN_XSA_FILE);
    std::printf("  driver db     : v%s\n", IPMAN_DB_VERSION);
    std::printf("  custom IP     : %d\n\n", IPMAN_IP_COUNT);

    std::printf("  %-18s %-34s %-12s %s\n", "INSTANCE", "VLNV", "BASE", "DRIVER");
    for (int i = 0; i < IPMAN_IP_COUNT; ++i) {
        const ipman_ip_info_t& ip = IPMAN_IPS[i];
        std::printf("  %-18s %-34s 0x%08lX   %s\n", ip.instance, ip.vlnv,
                    ip.base_addr, ip.driver[0] ? ip.driver : "(no driver)");
    }
    std::printf("\n");
}

}  // namespace

int main() {
    print_inventory();

#ifdef HAVE_PWM_CTRL
    // Two instances of the same IP share one driver build.
    std::printf("pwm_ctrl driver %s (built for IP %s)\n",
                acme::PwmCtrl::driver_version(),
                acme::PwmCtrl::built_for_ip_version());
    acme::PwmCtrl pwm0(PWM_CTRL_0_BASEADDR, "pwm_ctrl_0");
    acme::PwmCtrl pwm1(PWM_CTRL_1_BASEADDR, "pwm_ctrl_1");
    pwm0.enable(true);
    pwm0.set_duty(0, 250);
    pwm0.set_duty(1, 750);
    pwm1.enable(true);
    pwm1.set_duty(0, 500);
    for (const acme::PwmCtrl* pwm : {&pwm0, &pwm1}) {
        std::printf("  %-14s @0x%08lX enabled=%d duty=[%u, %u]\n",
                    pwm->instance().c_str(),
                    static_cast<unsigned long>(pwm->base()),
                    static_cast<int>(pwm->enabled()), pwm->duty(0), pwm->duty(1));
    }
    std::printf("\n");
#endif

#ifdef HAVE_ADC_STREAM
    std::printf("adc_stream driver %s\n", acme::AdcStream::driver_version());
    acme::AdcStream adc(ADC_STREAM_0_BASEADDR, "adc_stream_0");
    adc.start(/*continuous=*/true);
    const auto samples = adc.read_samples(4);
    std::printf("  %-14s @0x%08lX captured %u sample(s):",
                adc.instance().c_str(), static_cast<unsigned long>(adc.base()),
                adc.sample_count());
    for (std::uint32_t sample : samples) std::printf(" 0x%04X", sample);
    adc.stop();
    std::printf("\n\n");
#endif

#ifdef HAVE_AXI_GPIO_LITE
    std::printf("axi_gpio_lite driver %s\n", acme::AxiGpioLite::driver_version());
    acme::AxiGpioLite gpio(AXI_GPIO_LITE_0_BASEADDR, "axi_gpio_lite_0");
    gpio.set_direction(0xFFFF0000u);  // low half outputs
    gpio.write_pins(0x0000A5A5u);
    std::printf("  %-14s @0x%08lX tri=0x%08X pins=0x%08X\n\n",
                gpio.instance().c_str(), static_cast<unsigned long>(gpio.base()),
                gpio.direction(), gpio.read_pins());
#endif

    std::printf("all drivers exercised.\n");
    return 0;
}
