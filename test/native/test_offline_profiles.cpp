#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "FanController.h"
#include "ArgbController.h"
#include "CoolingController.h"
#include "OfflineProfiles.h"

int main() {
    FanController fans;
    ArgbController leds;
    assert(fans.begin());
    assert(leds.begin());
    CoolingController cooling(fans, Serial);
    assert(cooling.begin());
    OfflineProfiles bank(cooling,leds);
    assert(bank.begin());
    assert(bank.active()==0 && bank.boot()==0 && !bank.valid(1));
    assert(!bank.activate(1));

    // Capture currently persisted curve and an autonomous solid RGB scene.
    assert(leds.setSolid(0, 11, 22, 33));
    const size_t before = Preferences::writeCount();
    assert(bank.capture(1));
    assert(Preferences::writeCount()==before+1);
    assert(bank.valid(1) && !bank.valid(2));
    assert(bank.capture(1)); // unchanged snapshot, no NVS wear
    assert(Preferences::writeCount()==before+1);

    CoolingController::CurvePoint change[CoolingController::kCurvePoints] =
        {{25,55},{35,65},{50,80},{65,90},{80,100}};
    assert(cooling.setCurve(0,change));
    assert(leds.setOff(0));
    const size_t beforeSelect=Preferences::writeCount();
    assert(bank.activate(1));
    assert(cooling.offlineProfileActive());
    assert(leds.getMode(0)==ArgbController::Mode::Solid);
    uint8_t r=0,g=0,b=0;
    assert(leds.solidColor(0,r,g,b));
    assert(r==11 && g==22 && b==33);
    assert(Preferences::writeCount()==beforeSelect);
    assert(cooling.curve(0)[0].pwm==55); // saved base not overwritten
    assert(fans.getPercent(0)==100);     // unqualified DC key untouched
    assert(bank.clear() && !cooling.offlineProfileActive());
    assert(bank.active()==0 && cooling.curve(0)[0].pwm==55);

    // Explicit opt-in boot; switching profiles doesn't rewrite flash.
    assert(bank.setBoot(1));
    OfflineProfiles reloaded(cooling,leds);
    assert(reloaded.begin() && reloaded.active()==1 && reloaded.boot()==1);
    assert(cooling.offlineProfileActive());
    assert(Preferences::writeCount()==beforeSelect+1);
    assert(!reloaded.setBoot(2)); // not captured
    assert(reloaded.setBoot(0));

    // Failed capture cannot leave a partially saved bank.
    Preferences::failNextWrite();
    assert(!reloaded.capture(2));
    assert(!reloaded.valid(2));
    OfflineProfiles afterFail(cooling,leds);
    assert(afterFail.begin() && !afterFail.valid(2));
    // Sensor watchdog remains the authority, even in an offline profile.
    mock::currentMs=15000;
    cooling.update(mock::currentMs);
    assert(fans.getPercent(0)==100);
    std::cout << "PASS: three offline profiles, flash atomicity, boot opt-in and cooling guards\n";
}
