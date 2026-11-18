#include <cassert>
#include <iostream>
#include "Arduino.h"
#include "Preferences.h"
#include "ArgbController.h"

int main() {
    ArgbController leds;
    assert(leds.begin());
    argbaudio::Config cfg=argbaudio::defaults();
    cfg.style=2; cfg.gain=100;
    uint8_t frame[30*3]={};
    const argbaudio::Levels samples={190,90,40,200};
    argbaudio::render(cfg,samples,true,30,1000,frame);
    assert(frame[0]!=0 || frame[1]!=0 || frame[2]!=0);
    argbaudio::render(cfg,samples,false,30,1000,frame);
    for (auto value: frame) assert(value==0); // no stale music flicker
    const size_t before=Preferences::writeCount();
    assert(leds.setAudio(0,cfg));
    assert(leds.getMode(0)==ArgbController::Mode::Audio);
    assert(!leds.audioFresh(0));
    leds.setAudioLevels(samples,500);
    assert(leds.audioFresh(501));
    assert(!leds.audioFresh(1701));
    leds.setSafetyWarning(0,3);
    leds.update(1000);
    assert(leds.safetyWarning(0)==3);
    assert(leds.estimatedLimitedCurrent()<=leds.powerBudget());
    assert(Preferences::writeCount()==before);
    assert(leds.setAudioBoot(0,false));
    assert(leds.saveAudio());
    assert(Preferences::writeCount()==before+1);
    assert(leds.saveAudio());
    assert(Preferences::writeCount()==before+1);
    ArgbController restarted;
    assert(restarted.begin());
    assert(restarted.getMode(0)==ArgbController::Mode::Off);
    assert(restarted.audio(0).style==2);
    assert(restarted.setAudioBoot(0,true));
    assert(restarted.saveAudio());
    ArgbController optin;
    assert(optin.begin());
    assert(optin.getMode(0)==ArgbController::Mode::Audio);
    assert(optin.getMode(1)==ArgbController::Mode::Off);
    Preferences storage;
    assert(storage.begin("argb-v4",false));
    const char invalid[]={'b','a','d'};
    assert(storage.putBytes("audio",invalid,sizeof(invalid))==sizeof(invalid));
    ArgbController corrupted;
    assert(corrupted.begin());
    assert(corrupted.getMode(0)==ArgbController::Mode::Off);
    std::cout<<"PASS: numeric 4-band ESP audio, NVS opt-in, TTL and ARGB safety\n";
}
