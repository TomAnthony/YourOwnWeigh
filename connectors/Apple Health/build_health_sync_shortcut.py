#!/usr/bin/env python3
"""Build the distributable, credential-free YourOwnWeigh Health Shortcut."""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


HERE = Path(__file__).resolve().parent
APP_ICON = HERE.parents[1] / "design/app-icon/YourOwnWeigh-scale-teal.png"
PLACEHOLDER = "\ufffc"


def uid() -> str:
    return str(uuid.uuid4()).upper()


def action(identifier: str, **parameters: object) -> dict:
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions." + identifier,
        "WFWorkflowActionParameters": parameters,
    }


def output(identifier: str, name: str) -> dict:
    return {"Type": "ActionOutput", "OutputUUID": identifier, "OutputName": name}


def attachment(reference: dict) -> dict:
    return {"Value": reference, "WFSerializationType": "WFTextTokenAttachment"}


def token_string(parts: list[str | dict]) -> dict:
    characters = ""
    references = {}
    for part in parts:
        if isinstance(part, str):
            characters += part
        else:
            references[f"{{{len(characters)}, 1}}"] = part
            characters += PLACEHOLDER
    return {"Value": {"string": characters, "attachmentsByRange": references},
            "WFSerializationType": "WFTextTokenString"}


def text_action(value: str | dict, name: str) -> tuple[dict, str]:
    identifier = uid()
    return action("gettext", UUID=identifier, CustomOutputName=name,
                  WFTextActionText=value), identifier


def dictionary_value(key: str, source: str, source_name: str, name: str) -> tuple[dict, str]:
    identifier = uid()
    return action("getvalueforkey", UUID=identifier, CustomOutputName=name,
                  WFDictionaryKey=key, WFInput=attachment(output(source, source_name))), identifier


def http_headers(auth: dict) -> dict:
    return {"Value": {"WFDictionaryFieldValueItems": [
        {"WFItemType": 0, "WFKey": token_string(["Authorization"]),
         "WFValue": token_string(["Basic ", auth])},
        {"WFItemType": 0, "WFKey": token_string(["ngrok-skip-browser-warning"]),
         "WFValue": token_string(["true"])},
    ]}, "WFSerializationType": "WFDictionaryFieldValue"}


def main() -> None:
    actions: list[dict] = []
    actions.append(action("comment", WFCommentActionText=(
        "Before the first run, edit the three Text actions below. Include https:// in the server URL. "
        "The password stays in this Shortcut and syncs through your Apple Account. "
        "Install a separate copy for each person's own Apple Health account. "
        "Readings received since 2026-01-01 are eligible for import.")))
    actions.append(action("comment", WFCommentActionText=(
        "On each run, up to 100 readings are logged oldest first. The server marks each one imported "
        "only after the Health action finishes. If the request fails, check the server URL, "
        "Readings API password, and numeric user ID or three-letter display name.")))

    host_action, host = text_action("https://your-server.example", "Server URL")
    password_action, password = text_action("ENTER_API_PASSWORD", "API Password")
    user_action, user = text_action("ENTER_USER_ID_OR_SHORT_NAME", "User ID or Short Name")
    actions.extend([host_action, password_action, user_action])

    credentials_action, credentials = text_action(token_string(["reader:", output(password, "API Password")]),
                                                  "Basic Credentials")
    actions.append(credentials_action)
    encoded = uid()
    actions.append(action("base64encode", UUID=encoded, CustomOutputName="Encoded Credentials",
                          WFEncodeMode="Encode", WFBase64LineBreakMode="None",
                          WFInput=attachment(output(credentials, "Basic Credentials"))))
    auth = output(encoded, "Encoded Credentials")

    repeat_group = uid()
    actions.append(action("repeat.count", GroupingIdentifier=repeat_group,
                          WFControlFlowMode=0, WFRepeatCount=100))
    endpoint = token_string([output(host, "Server URL"), "/api/users/", output(user, "User ID or Short Name"),
                             "/health-sync/next?since=2026-01-01"])
    next_request = uid()
    actions.append(action("downloadurl", UUID=next_request, CustomOutputName="Next Reading Response",
                          WFURL=endpoint, WFHTTPMethod="GET", WFHTTPHeaders=http_headers(auth)))

    response_text = uid()
    actions.append(action("detect.text", UUID=response_text, CustomOutputName="Response Text",
                          WFInput=attachment(output(next_request, "Next Reading Response"))))
    response_group = uid()
    actions.append(action("conditional", GroupingIdentifier=response_group, WFControlFlowMode=0,
                          WFCondition=99, WFConditionalActionString='"reading":',
                          WFInput={"Type": "Variable", "Variable":
                                   attachment(output(response_text, "Response Text"))}))
    response_dictionary = uid()
    actions.append(action("detect.dictionary", UUID=response_dictionary,
                          CustomOutputName="JSON Response",
                          WFInput=attachment(output(response_text, "Response Text"))))
    actions.append(action("conditional", GroupingIdentifier=response_group, WFControlFlowMode=1))
    actions.append(action("alert",
                          WFAlertActionTitle=token_string(["YourOwnWeigh Sync Failed"]),
                          WFAlertActionMessage=token_string([
                              "The server did not return a reading. Check the full https:// URL, "
                              "Readings API password, and user ID or three-letter display name."]),
                          WFAlertActionCancelButtonShown=False))
    actions.append(action("exit"))
    actions.append(action("conditional", GroupingIdentifier=response_group, WFControlFlowMode=2))

    reading_action, reading = dictionary_value("reading", response_dictionary, "JSON Response", "Reading")
    actions.append(reading_action)

    condition_group = uid()
    actions.append(action("conditional", GroupingIdentifier=condition_group, WFControlFlowMode=0,
                          WFCondition=100, WFInput={"Type": "Variable", "Variable":
                          attachment(output(reading, "Reading"))}))
    weight_action, weight = dictionary_value("weight_kg", reading, "Reading", "Weight kg")
    date_action, date_text = dictionary_value("date", reading, "Reading", "Reading Date")
    id_action, reading_id = dictionary_value("id", reading, "Reading", "Reading ID")
    actions.extend([weight_action, date_action, id_action])

    # Never acknowledge a missing weight. The Health quantity below must remain
    # a direct action-output reference; a token string writes 0 kg.
    weight_present_group = uid()
    actions.append(action("conditional", GroupingIdentifier=weight_present_group,
                          WFControlFlowMode=0, WFCondition=100,
                          WFInput={"Type": "Variable", "Variable":
                                   attachment(output(weight, "Weight kg"))}))

    date_value = uid()
    actions.append(action("date", UUID=date_value, WFDateActionMode="Specified Date",
                          WFDateActionDate=token_string([output(date_text, "Reading Date")])))
    actions.append(action("health.quantity.log", UUID=uid(), WFQuantitySampleType="Weight",
                          WFQuantitySampleQuantity={"Value": {
                              "Magnitude": output(weight, "Weight kg"), "Unit": "kg"},
                              "WFSerializationType": "WFQuantityFieldValue"},
                          WFQuantitySampleDate=attachment(output(date_value, "Date"))))

    ack_url = token_string([output(host, "Server URL"), "/api/users/", output(user, "User ID or Short Name"),
                            "/health-sync/ack?reading_id=", output(reading_id, "Reading ID")])
    actions.append(action("downloadurl", UUID=uid(), WFURL=ack_url, WFHTTPMethod="POST",
                          WFHTTPHeaders=http_headers(auth)))
    actions.append(action("conditional", GroupingIdentifier=weight_present_group,
                          WFControlFlowMode=1))
    actions.append(action("alert",
                          WFAlertActionTitle=token_string(["Invalid Weight"]),
                          WFAlertActionMessage=token_string([
                              "The server returned no weight. Nothing was written "
                              "to Apple Health or acknowledged. Please check this reading on the server."]),
                          WFAlertActionCancelButtonShown=False))
    actions.append(action("exit"))
    actions.append(action("conditional", GroupingIdentifier=weight_present_group,
                          WFControlFlowMode=2))
    actions.append(action("conditional", GroupingIdentifier=condition_group, WFControlFlowMode=1))
    actions.append(action("exit"))
    actions.append(action("conditional", GroupingIdentifier=condition_group, WFControlFlowMode=2))
    actions.append(action("repeat.count", GroupingIdentifier=repeat_group, WFControlFlowMode=2, UUID=uid()))

    workflow = {
        "WFWorkflowName": "YourOwnWeigh Sync",
        "WFWorkflowActions": actions,
        "WFWorkflowClientVersion": "2700.0.4",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        # Shortcuts tiles accept a palette colour and built-in glyph. The matching
        # app artwork is copied below for an exact Home Screen icon on iPhone.
        "WFWorkflowIcon": {"WFWorkflowIconGlyphNumber": 59834, "WFWorkflowIconStartColor": 431817727},
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowTypes": [],
        "WFWorkflowHasOutputFallback": False,
    }
    unsigned = HERE / "YourOwnWeigh Sync.unsigned.plist"
    signed = HERE / "YourOwnWeigh Sync.shortcut"
    shutil.copyfile(APP_ICON, HERE / "YourOwnWeigh Home Screen Icon.png")
    unsigned.write_bytes(plistlib.dumps(workflow, fmt=plistlib.FMT_XML, sort_keys=False))
    with tempfile.TemporaryDirectory(prefix="yow-shortcut-") as temporary:
        unsigned_binary = Path(temporary) / "unsigned.shortcut"
        unsigned_binary.write_bytes(plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY, sort_keys=False))
        subprocess.run(["shortcuts", "sign", "--mode", "anyone", "--input", str(unsigned_binary),
                        "--output", str(signed)], check=True)
    print(f"Built {signed}")


if __name__ == "__main__":
    main()
