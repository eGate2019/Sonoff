from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.light import LightEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity

from ..binary_sensor import (
    XBinarySensor,
    XHumanSensor,
    XLightSensor,
    XWaterSensor,
    XWiFiDoor,
    XZigbeeMotion,
)
from ..climate import XClimateNS, XClimateTH, XThermostat
from ..core.entity import XEntity
from ..cover import XCover, XCover91, XCoverDualR3, XZigbeeCover
from ..fan import XDiffuserFan, XFan, XFanDualR3, XToggleFan
from ..light import (
    XDiffuserLight,
    XDimmer,
    XFanLight,
    XLight57,
    XLightB02,
    XLightB05B,
    XLightB1,
    XLightD1,
    XLightGroup,
    XLightL1,
    XLightL3,
    XOnOffLight,
    XT5Light,
    XZigbeeLight,
)
from ..number import XPulseWidth, XSensitivity
from ..remote import XRemote
from ..sensor import (
    XEnergySensor,
    XEnergySensorDualR3,
    XEnergySensorPOWR3,
    XEnergyTotal,
    XHumidityTH,
    XOutdoorTempNS,
    XRemoteButton,
    XSensor,
    XT5Action,
    XTemperatureNS,
    XTemperatureTH,
    XUnknown,
    XWiFiDoorBattery,
)
from ..switch import (
    XBoolSwitch,
    XDetach,
    XSwitch,
    XSwitches,
    XSwitchPOWR3,
    XSwitchTH,
    XToggle,
    XZigbeeSwitches,
)
from .ewelink import XDevice

# Supported custom device classes
DEVICE_CLASS = {
    "binary_sensor": (XEntity, BinarySensorEntity),
    "fan": (XToggleFan,),  # Custom class for overriding is_on function
    "light": (XOnOffLight,),  # Fix color modes support
    "sensor": (XEntity, SensorEntity),
    "switch": (XEntity, SwitchEntity),
}

def unwrap_cached_properties(attrs: dict):
    """Fix metaclass CachedProperties problem in latest Hass."""
    for k, v in list(attrs.items()):
        if k.startswith("_attr_") and f"_{k}" in attrs and isinstance(v, property):
            attrs[k] = attrs.pop(f"_{k}")
    return attrs

def spec(cls, base: str = None, enabled: bool = None, **kwargs) -> type:
    """Make duplicate for cls class with changes in kwargs params.

    If `base` param provided - can change Entity base class for cls.
    So it can be added to different Hass domain.
    """

    if enabled is not None:
        kwargs["_attr_entity_registry_enabled_default"] = enabled

    if base:
        attrs = cls.__mro__[-len(XSwitch.__mro__) :: -1]
        attrs = {k: v for b in attrs for k, v in b.__dict__.items()}
        attrs = unwrap_cached_properties({**attrs, **kwargs})
        return type(cls.__name__, DEVICE_CLASS[base], attrs)

    return type(cls.__name__, (cls,), kwargs)

# Define specific switch instances with unique identifiers
Switch1 = spec(XSwitches, channel=0, uid="1")
Switch2 = spec(XSwitches, channel=1, uid="2")
Switch3 = spec(XSwitches, channel=2, uid="3")
Switch4 = spec(XSwitches, channel=3, uid="4")

# Define sensor specifications with modified parameters
XSensor100 = spec(XSensor, multiply=0.01, round=2)
Battery = spec(XSensor, param="battery")
LED = spec(XToggle, param="sledOnline", uid="led", enabled=False)
RSSI = spec(XSensor, param="rssi", enabled=False)
PULSE = spec(XToggle, param="pulse", enabled=False)
ZRSSI = spec(XSensor, param="subDevRssi", uid="rssi", enabled=False)

# Define specifications for different switch configurations
SPEC_SWITCH = [XSwitch, LED, RSSI]
SPEC_1CH = [Switch1] + SPEC_SWITCH
SPEC_2CH = [Switch1, Switch2] + SPEC_SWITCH
SPEC_3CH = [Switch1, Switch2, Switch3] + SPEC_SWITCH
SPEC_4CH = [Switch1, Switch2, Switch3, Switch4] + SPEC_SWITCH

# Define current and voltage specifications for sensors
Current1 = spec(XSensor100, param="current_00", uid="current_1")
Current2 = spec(XSensor100, param="current_01", uid="current_2")
Current3 = spec(XSensor100, param="current_02", uid="current_3")
Current4 = spec(XSensor100, param="current_03", uid="current_4")

Voltage1 = spec(XSensor100, param="voltage_00", uid="voltage_1")
Voltage2 = spec(XSensor100, param="voltage_01", uid="voltage_2")
Voltage3 = spec(XSensor100, param="voltage_02", uid="voltage_3")
Voltage4 = spec(XSensor100, param="voltage_03", uid="voltage_4")

Power1 = spec(XSensor100, param="actPow_00", uid="power_1")
Power2 = spec(XSensor100, param="actPow_01", uid="power_2")
Power3 = spec(XSensor100, param="actPow_02", uid="power_3")
Power4 = spec(XSensor100, param="actPow_03", uid="power_4")

EnergyPOW = spec(
    XEnergySensor,
    param="hundredDaysKwhData",
    uid="energy",
    get_params={"hundredDaysKwh": "get"},
)

# Backward compatibility for unique_id
DoorLock = spec(XBinarySensor,param="lock",uid="",default_class="door")

# Device specifications mapping based on UIID
DEVICES = {
   1: SPEC_SWITCH,
   2: SPEC_2CH,
   3: SPEC_3CH,
   4: SPEC_4CH,
   5: [
       XSwitch,
       LED,
       RSSI,
       spec(XSensor,param="power"),
       EnergyPOW,
   ],  # Sonoff POW (first)
   6: SPEC_SWITCH,
   7: SPEC_2CH,# Sonoff T1 2CH
   8: SPEC_3CH,# Sonoff T1 3CH
   9: SPEC_4CH,
   11: [XCover,RSSI], # King Art - King Q4 Cover (only cloud)
   14: SPEC_SWITCH,# Sonoff Basic (3rd party)
   15: [
       XClimateTH,XTemperatureTH,XHumidityTH,RSSI,RSSI],
   # Sonoff TH16
   # Additional device specifications...
}

def get_spec(device: dict) -> list:
    """Retrieve the specifications for a given device."""

    uiid = device["extra"]["uiid"]

    if uiid in DEVICES:
        classes = DEVICES[uiid]

    elif "switch" in device["params"]:
        classes = SPEC_SWITCH

    elif "switches" in device["params"]:
        classes = SPEC_4CH

    else:
        classes = [XUnknown]  # Default to unknown class

    # Handle specific cases based on UIID and parameters.
    if uiid in [126 ,165] and device["params"].get("workMode") == 2:
        classes=[cls for cls in classes if not cls.__bases__==XSwitches]
        classes=[XCoverDualR3,XFanDualR3]+classes

    if uiid in [133] and not device["params"].get("HMI_ATCDevice"):
        classes=[cls for cls in classes if not cls.__bases__==XClimateNS]

    if uiid in [2026] and not device["params"].get("battery"):
        classes=[cls for cls in classes if cls != Battery]

    if "device_class" in device:
        classes=get_custom_spec(classes ,device["device_class"])

    return classes

def get_custom_spec(classes: list ,device_class):
     """Get custom specifications based on the provided device class."""

     # Supported formats for device_class handling.

     # Single channel specification.
     if isinstance(device_class ,str):
         if device_class in DEVICE_CLASS:
             classes=[spec(classes[0] ,base=device_class)]+classes[1:]

     elif isinstance(device_class ,list):
         # Remove default multichannel classes from specification.
         base=classes[0].__base__
         classes=[cls for cls in classes if base not in cls.__bases__]

         for i ,sub_class in enumerate(device_class):
             # Simple multichannel specification.
             if isinstance(sub_class ,str):
                 classes.append(spec(base ,channel=i ,uid=str(i + 1) ,base=sub_class))

             elif isinstance(sub_class ,dict):
                 sub_class,i=next(iter(sub_class.items()))

                 # Light with brightness control.
                 if isinstance(i ,list) and sub_class=="light":
                     chs=[x - 1 for x in i]
                     uid ="".join(str(x) for x in i)
                     classes.append(spec(XLightGroup ,channels=chs ,uid=uid))

                 # Multichannel specification.
                 elif isinstance(i,int):
                     classes.append(spec(base ,channel=(i - 1),uid=str(i),base=sub_class))

     return classes

def get_spec_wrapper(func,sensors:list):
     """Wrap specification function to include additional sensors."""

     def wrapped(device: dict) -> list:
         """Wrapped function to modify returned class list."""

         classes=func(device)

         for uid in sensors:
             if (uid in device["params"] or uid == "host") and all(
                     cls.param != uid and cls.uid != uid for cls in classes):
                 classes.append(spec(XSensor,param=uid))

         return classes

     return wrapped

def set_default_class(device_class:str):
     """Set default class based on the specified device class."""

     # Adjust base class depending on the type of device.
     if device_class=="light":
         LightEntity.__bases__=(XEntity,)

     else:
         SwitchEntity.__bases__=(XEntity,)

# Cloud definitions for DIY devices.
DIY={
     "plug":[1,None,"Single Channel DIY"],
     "strip":[4,None,"Multi Channel DIY"],
     "diy_plug":[1,"SONOFF","MINI DIY"],
     "enhanced_plug":[5,"SONOFF","POW DIY"],
     "th_plug":[15,"SONOFF","TH DIY"],
}

def setup_diy(device: dict) ->XDevice:
    """Setup a DIY device based on its local type."""

    ltype=device["localtype"]

    try:
        uiid ,brand ,model=DIY[ltype]

        # Handle specific cases based on local type.

        if ltype=="diy_plug" and "switches" in device["params"]:
            uiid=77
            model ="MINI R3 DIY"

        device["name"]=model
        device["brandName"]=brand
        device["extra"]={"uiid":uiid}
        device["productModel"] = model
    except Exception:
        device["name"] = "Unknown DIY"
        device["extra"] = {"uiid": 0}
        device["productModel"] = ltype
        return device
