from openpilot.common.numpy_fast import clip
from openpilot.selfdrive.car import CanBusBase
from openpilot.selfdrive.car.hyundai.values import HyundaiFlags, HyundaiExtFlags
from openpilot.common.params import Params


class CanBus(CanBusBase):
  def __init__(self, CP, hda2=None, fingerprint=None) -> None:
    super().__init__(CP, fingerprint)

    if hda2 is None:
      assert CP is not None
      hda2 = CP.flags & HyundaiFlags.CANFD_HDA2.value

    # On the CAN-FD platforms, the LKAS camera is on both A-CAN and E-CAN. HDA2 cars
    # have a different harness than the HDA1 and non-HDA variants in order to split
    # a different bus, since the steering is done by different ECUs.
    self._a, self._e = 1, 0
    if hda2 and Params().get_int("SccConnectedBus2") == 0:  #배선개조는 무조건 Bus0가 ECAN임.
      self._a, self._e = 0, 1

    if Params().get_int("SccConnectedBus2") == 2:
      self.offset = 0

    self._a += self.offset
    self._e += self.offset
    self._cam = 2 + self.offset

  @property
  def ECAN(self):
    return self._e

  @property
  def ACAN(self):
    return self._a

  @property
  def CAM(self):
    return self._cam

def create_steering_messages_scc2(packer, CP, CAN, enabled, lat_active, apply_steer, lfa_info):

  values = lfa_info
  values["LKA_MODE"] = 2
  values["LKA_ICON"] = 2 if enabled else 1
  values["TORQUE_REQUEST"] = apply_steer
  values["LKA_ASSIST"] = 0
  values["STEER_REQ"] = 1 if lat_active else 0
  values["STEER_MODE"] = 0
  values["HAS_LANE_SAFETY"] = 0  # hide LKAS settings
  values["NEW_SIGNAL_1"] = 0  
  values["NEW_SIGNAL_2"] = 0  

  return packer.make_can_msg("LFA", CAN.ECAN, values)

def create_steering_messages(packer, CP, CAN, enabled, lat_active, apply_steer):

  ret = []

  values = {
    "LKA_MODE": 2,
    "LKA_ICON": 2 if enabled else 1,
    "TORQUE_REQUEST": apply_steer,
    "LKA_ASSIST": 0,
    "STEER_REQ": 1 if lat_active else 0,
    "STEER_MODE": 0,
    "HAS_LANE_SAFETY": 0,  # hide LKAS settings
    "NEW_SIGNAL_1": 0,
    "NEW_SIGNAL_2": 0,
  }

  if CP.flags & HyundaiFlags.CANFD_HDA2:
    hda2_lkas_msg = "LKAS_ALT" if CP.flags & HyundaiFlags.CANFD_HDA2_ALT_STEERING else "LKAS"
    if CP.openpilotLongitudinalControl: # and not (CP.extFlags & HyundaiExtFlags.ACAN_PANDA.value):
      ret.append(packer.make_can_msg("LFA", CAN.ECAN, values))
    if not (CP.extFlags & HyundaiExtFlags.SCC_BUS2.value) or CP.extFlags & HyundaiExtFlags.ACAN_PANDA.value:
      ret.append(packer.make_can_msg(hda2_lkas_msg, CAN.ACAN, values))
  else:
    ret.append(packer.make_can_msg("LFA", CAN.ECAN, values))

  return ret

def create_suppress_lfa_scc2(packer, CAN, hda2_alt_steering, counter):
  suppress_msg = "CAM_0x362" if hda2_alt_steering else "CAM_0x2a4"
  msg_bytes = 32 if hda2_alt_steering else 24

  values = {}
  values["BYTE5"] = 34
  values["BYTE8"] = 34
  values["COUNTER"] = counter % 256
  values["SET_ME_0"] = 0
  values["SET_ME_0_2"] = 0
  values["LEFT_LANE_LINE"] = 0
  values["RIGHT_LANE_LINE"] = 0
  return packer.make_can_msg(suppress_msg, CAN.ACAN, values)

def create_suppress_lfa(packer, CAN, hda2_lfa_block_msg, hda2_alt_steering):
  suppress_msg = "CAM_0x362" if hda2_alt_steering else "CAM_0x2a4"
  msg_bytes = 32 if hda2_alt_steering else 24

  values = {f"BYTE{i}": hda2_lfa_block_msg[f"BYTE{i}"] for i in range(3, msg_bytes) if i != 7}
  values["COUNTER"] = hda2_lfa_block_msg["COUNTER"]
  values["SET_ME_0"] = 0
  values["SET_ME_0_2"] = 0
  values["LEFT_LANE_LINE"] = 0
  values["RIGHT_LANE_LINE"] = 0
  return packer.make_can_msg(suppress_msg, CAN.ACAN, values)

def create_buttons(packer, CP, CAN, cnt, btn):
  values = {
    "COUNTER": cnt,
    "SET_ME_1": 1,
    "CRUISE_BUTTONS": btn,
  }

  bus = CAN.ECAN if CP.flags & HyundaiFlags.CANFD_HDA2 else CAN.CAM
  return packer.make_can_msg("CRUISE_BUTTONS", bus, values)

def create_acc_cancel(packer, CP, CAN, cruise_info_copy):
  # TODO: why do we copy different values here?
  if CP.flags & HyundaiFlags.CANFD_CAMERA_SCC.value:
    values = {s: cruise_info_copy[s] for s in [
      "COUNTER",
      "CHECKSUM",
      "NEW_SIGNAL_1",
      "MainMode_ACC",
      "ACCMode",
      "ZEROS_9",
      "CRUISE_STANDSTILL",
      "ZEROS_5",
      "DISTANCE_SETTING",
      "VSetDis",
    ]}
  else:
    values = {s: cruise_info_copy[s] for s in [
      "COUNTER",
      "CHECKSUM",
      "ACCMode",
      "VSetDis",
      "CRUISE_STANDSTILL",
    ]}
  values.update({
    "ACCMode": 4,
    "aReqRaw": 0.0,
    "aReqValue": 0.0,
  })
  return packer.make_can_msg("SCC_CONTROL", CAN.ECAN, values)

def create_lfahda_cluster(packer, CAN, enabled):
  values = {
    "HDA_ICON": 1 if enabled else 0,
    "LFA_ICON": 2 if enabled else 0,
  }
  return packer.make_can_msg("LFAHDA_CLUSTER", CAN.ECAN, values)


def create_acc_control_scc2(packer, CAN, enabled, accel_last, accel, stopping, gas_override, set_speed, hud_control, jerk_u, jerk_l, cruise_info_copy):
  enabled = enabled or hud_control.softHold > 0
  jerk = 5
  jn = jerk / 50
  if not enabled or gas_override:
    a_val, a_raw = 0, 0
  else:
    a_raw = accel
    a_val = clip(accel, accel_last - jn, accel_last + jn)

  values = cruise_info_copy
  values["ACCMode"] = 0 if not enabled else (2 if gas_override else 1)
  values["MainMode_ACC"] = 1
  values["StopReq"] = 1 if stopping or hud_control.softHold > 0 else 0
  values["aReqValue"] = a_val
  values["aReqRaw"] = a_raw
  values["VSetDis"] = set_speed
  #values["JerkLowerLimit"] = jerk if enabled else 1
  #values["JerkUpperLimit"] = 3.0
  values["JerkLowerLimit"] = jerk_l if enabled else 1
  values["JerkUpperLimit"] = jerk_u
  values["DISTANCE_SETTING"] = hud_control.leadDistanceBars

  values["ACC_ObjDist"] = 1
  values["ObjValid"] = 0
  values["OBJ_STATUS"] =  2
  values["SET_ME_2"] = 0x4
  values["SET_ME_3"] = 0x3
  values["SET_ME_TMP_64"] = 0x64

  values["NEW_SIGNAL_3"] = 0  # 1이되면 차선이탈방지 알람이 뜬다고...
  return packer.make_can_msg("SCC_CONTROL", CAN.ECAN, values)

def create_acc_control(packer, CAN, enabled, accel_last, accel, stopping, gas_override, set_speed, hud_control, jerk_u, jerk_l):
  enabled = enabled or hud_control.softHold > 0
  jerk = 5
  jn = jerk / 50
  if not enabled or gas_override:
    a_val, a_raw = 0, 0
  else:
    a_raw = accel
    a_val = clip(accel, accel_last - jn, accel_last + jn)

  values = {
    "ACCMode": 0 if not enabled else (2 if gas_override else 1),
    "MainMode_ACC": 1,
    "StopReq": 1 if stopping or hud_control.softHold > 0 else 0,
    "aReqValue": a_val,
    "aReqRaw": a_raw,
    "VSetDis": set_speed,
    #"JerkLowerLimit": jerk if enabled else 1,
    #"JerkUpperLimit": 3.0,
    "JerkLowerLimit": jerk_l if enabled else 1,
    "JerkUpperLimit": jerk_u,

    "ACC_ObjDist": 1,
    "ObjValid": 0,
    "OBJ_STATUS": 2,
    "SET_ME_2": 0x4,
    "SET_ME_3": 0x3,
    "SET_ME_TMP_64": 0x64,
    "DISTANCE_SETTING": hud_control.leadDistanceBars,
  }

  return packer.make_can_msg("SCC_CONTROL", CAN.ECAN, values)


def create_spas_messages(packer, CAN, frame, left_blink, right_blink):
  ret = []

  values = {
  }
  ret.append(packer.make_can_msg("SPAS1", CAN.ECAN, values))

  blink = 0
  if left_blink:
    blink = 3
  elif right_blink:
    blink = 4
  values = {
    "BLINKER_CONTROL": blink,
  }
  ret.append(packer.make_can_msg("SPAS2", CAN.ECAN, values))

  return ret


def create_fca_warning_light(packer, CAN, frame):
  ret = []
  if frame % 2 == 0:
    values = {
      'AEB_SETTING': 0x1,  # show AEB disabled icon
      'SET_ME_2': 0x2,
      'SET_ME_FF': 0xff,
      'SET_ME_FC': 0xfc,
      'SET_ME_9': 0x9,
      #'DATA102': 1,
    }
    ret.append(packer.make_can_msg("ADRV_0x160", CAN.ECAN, values))
  return ret


def create_adrv_messages(CP, packer, CAN, frame):
  # messages needed to car happy after disabling
  # the ADAS Driving ECU to do longitudinal control

  ret = []

  values = {
  }
  if not (CP.extFlags & HyundaiExtFlags.SCC_BUS2.value) or CP.extFlags & HyundaiExtFlags.ACAN_PANDA.value:
    ret.append(packer.make_can_msg("ADRV_0x51", CAN.ACAN, values))

  if not (CP.extFlags & HyundaiExtFlags.SCC_BUS2.value):
    ret.extend(create_fca_warning_light(packer, CAN, frame))
    if frame % 5 == 0:
      values = {
        'SET_ME_1C': 0x1c,
        'SET_ME_FF': 0xff,
        'SET_ME_TMP_F': 0xf,
        'SET_ME_TMP_F_2': 0xf,
        #'DATA26': 1,  #1
        #'DATA32': 5,  #5
      }
      ret.append(packer.make_can_msg("ADRV_0x1ea", CAN.ECAN, values))

      values = {
        'SET_ME_E1': 0xe1,
        'SET_ME_3A': 0x3a,
      }
      ret.append(packer.make_can_msg("ADRV_0x200", CAN.ECAN, values))

    if frame % 20 == 0:
      values = {
        'SET_ME_15': 0x15,
      }
      ret.append(packer.make_can_msg("ADRV_0x345", CAN.ECAN, values))

    if frame % 100 == 0:
      values = {
        'SET_ME_22': 0x22,
        'SET_ME_41': 0x41,
      }
      ret.append(packer.make_can_msg("ADRV_0x1da", CAN.ECAN, values))

  return ret

## carrot
def alt_cruise_buttons(packer, CP, CAN, buttons, cruise_btns_msg, cnt):
  cruise_btns_msg["CRUISE_BUTTONS"] = buttons
  cruise_btns_msg["COUNTER"] = (cruise_btns_msg["COUNTER"] + 1 + cnt) % 256
  return packer.make_can_msg("CRUISE_BUTTONS_ALT", CAN.ECAN, cruise_btns_msg)
