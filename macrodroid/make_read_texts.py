"""Build "Read texts aloud.macro": a MacroDroid macro that speaks
"<sender> says: <first 5 words>" when a messaging app posts a notification.

Import: push the file, then open it in MacroDroid through MediaStore with a
read grant (MacroDroid has no storage permission, so file:// fails):
  adb push "Read texts aloud.macro" /sdcard/Download/read_texts_aloud.macro
  adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE \
      -d file:///sdcard/Download/read_texts_aloud.macro
  adb shell content query --uri content://media/external/file --projection _id \
      --where "\"_data LIKE '%read_texts_aloud.macro'\""
  adb shell am start -a android.intent.action.VIEW -t application/mdr \
      -d content://media/external/file/<_id> --grant-read-uri-permission \
      -n com.arlosoft.macrodroid/.filehandler.FileHandlerProxy
Use .macro (single-macro format), not .mdr (full-backup format).

KNOWN GAP (MacroDroid 6.0.11): the Speak Text action below is silently dropped
on import. Add it by hand in the editor: Speak Text, text
"{not_title} says: {lv=short}", drag Pitch to 100 and Speed to 75, tick "Queue text"
and "Skip emojis", then save.
After import, check Constraints shows "Priority Mode / Do Not Disturb: In mode:
Allow All"; if it is missing, add it by hand the same way.

Also grant DND access so the constraint can read the mode:
  adb shell cmd notification allow_dnd com.arlosoft.macrodroid"""
import json
import random
import sys

CHAT_APPS = [  # (label, package) — read aloud all notifications with sound
    ("Messenger", "com.facebook.orca"),
    ("Signal", "org.thoughtcrime.securesms"),
    ("Chat", "com.google.android.apps.dynamite"),
    ("Facebook", "com.facebook.katana"),
]
SMS_APPS = [  # (label, package) — read aloud only when from Denken or Sophia
    ("Voice", "com.google.android.apps.googlevoice"),
    ("Messages", "com.google.android.apps.messaging"),
    ("Messages", "com.samsung.android.messaging"),
]
SMS_ALLOWED_TITLE_REGEX = r"^(?i)\s*(Denken|Sophia(\s+Cardenas)?)\s*$"
WORDS = 6


def guid():
    return random.randint(-2**63, 2**63 - 1)


def local_var(name):
    return {"dictionary": {"entries": [], "isArray": False, "variableType": 4, "type": "Dictionary"},
            "isActionBlockWorkingVar": False, "isLocalVar": True, "isSecure": False,
            "m_booleanValue": False, "m_decimalValue": 0.0, "m_intValue": 0, "m_name": name,
            "m_stringValue": "", "m_type": 2, "supportsInput": False, "supportsOutput": True}


def common(cls):
    return {"disableLogging": False, "m_SIGUID": guid(), "m_classType": cls, "m_comment": "",
            "m_constraintList": [], "m_isDisabled": False, "m_isOrCondition": False}


chat_trigger = {
    "enableRegex": False, "ignoreCase": True,
    "m_applicationNameList": [a for a, _ in CHAT_APPS], "m_packageNameList": [p for _, p in CHAT_APPS],
    "m_exactMatch": False, "m_excludeApps": False, "m_excludes": False,
    "m_ignoreOngoing": True, "m_option": 0, "m_soundOption": 1, "m_supressMultiples": True,
    "m_textContent": "", "matchOptionMessage": 0, "matchOptionTitle": 0,
    "separateTitleAndMessage": False,
    **common("NotificationTrigger"),
}
sms_trigger = {
    "enableRegex": True, "ignoreCase": True,
    "m_applicationNameList": [a for a, _ in SMS_APPS], "m_packageNameList": [p for _, p in SMS_APPS],
    "m_exactMatch": False, "m_excludeApps": False, "m_excludes": False,
    "m_ignoreOngoing": True, "m_option": 0, "m_soundOption": 1, "m_supressMultiples": True,
    "m_textContent": "", "matchOptionMessage": 0, "matchOptionTitle": 1,
    "messageContent": "", "separateTitleAndMessage": True,
    "titleContent": SMS_ALLOWED_TITLE_REGEX,
    **common("NotificationTrigger"),
}
shorten = {  # first WORDS words of the message body -> local var "short"
    "m_option": 2, "m_text": "{notification}",
    "m_textManipulation": {"type": "ExtractTextManipulation",
                           "params": [r"^\S+(\s+\S+){0,%d}" % (WORDS - 1), "0"]},
    "m_variable": local_var("short"), "variableName": "short",
    **common("TextManipulationAction"),
}
speak = {
    "m_audioStream": 0, "m_pitch": 2.0, "m_queue": True,
    "m_readNumbersIndividually": False, "m_skipEmojis": True,
    "m_specifyAudioStream": False, "m_speed": 1.5,
    "m_textToSay": "{not_title} says: {lv=short}", "m_waitToFinish": False,
    **common("SpeakTextAction"),
}
dnd_off = {  # only run while Do Not Disturb is off ("In mode: Allow All"); TTS ignores DND
    "m_inMode": True, "m_selectedIndex": 0,
    **common("PriorityModeConstraint"),
}
macro = {
    "macroExportVersion": 1, "globalVariables": [],
    "macro": {
        "aiGenerated": 0, "breakpoints": [], "disabledTimestamp": 0, "exportedActionBlocks": [],
        "forceEvenIfNotEnabledTimestamp": 0, "isActionBlock": False, "isExtra": False,
        "isFavourite": False, "lastEditedTimestamp": 0, "localVariables": [local_var("short")],
        "localVarsAlphabetical": True, "m_GUID": guid(), "m_category": "Uncategorized",
        "m_constraintList": [dnd_off], "m_description": "Speak the sender and first %d words of new messages." % WORDS,
        "m_descriptionOpen": False, "m_enabled": True, "m_excludeLog": False, "m_headingColor": 0,
        "m_isOrCondition": False, "m_name": "Read texts aloud",
        "m_triggerList": [chat_trigger, sms_trigger], "m_actionList": [shorten, speak],
    },
}
json.dump(macro, open(sys.argv[1] if len(sys.argv) > 1 else "Read texts aloud.macro", "w"), indent=1)
