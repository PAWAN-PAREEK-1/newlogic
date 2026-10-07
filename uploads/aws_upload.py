"""Handle S3 connection and file upload using .env credentials"""

import time
import warnings
import boto3
from uploads.aws_constants import ACCESS_KEY, SECRET_KEY, BUCKET_NAME
from uploads.aws_classes import AWSCommands, check_files, FileDetails


def upload_to_aws(gamestate, game_modes, upload_obj, override_check=False):
    """Verify file details and upload to S3 bucket."""
    game_to_upload = gamestate.config.game_id
    failed_rtp_check = True
    s3_client = boto3.resource("s3", aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY)

    print("**************************")
    print("\n Avaliable S3 Buckets:\n")
    buckets = [bucket.name for bucket in s3_client.buckets.all()]
    [print(b) for b in buckets]
    print("**************************\n")

    # Read config and compare names, file hash and book length
    if not override_check:
        test_game = check_files(game_to_upload)
        json_data, game_modes = test_game.file_checker()  # type:ignore
        all_file_details = test_game.get_file_characteristics(json_data, game_modes)
        failed_count = test_game.compare_file_values(all_file_details)
        if not failed_count:
            raise ValueError("Failed File Checks!")
        else:
            print("\nConfig File Checks Successful\n")
    else:
        print("Config File Checks Overridden!")
        time.sleep(3)

    bucket_folder = game_to_upload + "/"
    file_details = FileDetails(game_to_upload, game_modes)
    aws_details = AWSCommands(s3_client, BUCKET_NAME, bucket_folder)

    all_files = file_details.get_file_paths(
        books=upload_obj["books"],
        config_files=upload_obj["config_files"],
        force_files=upload_obj["force_files"],
        lookupTables=upload_obj["lookup_tables"],
    )
    if upload_obj["lookup_tables"]:
        failed_rtp_check = file_details.check_rtp(game_modes)

        if failed_rtp_check:
            user_resp = input("Game Failed RTP Checker. Upload anyway? (y/n)")
            if user_resp.upper() in ["Y", "YES", "1"]:
                warnings.warn("RTP Checks Overridden!")
            else:
                raise RuntimeError("Failed RTP Check...aborting upload")

    if not override_check:
        check_config = file_details.check_config_details()
        if not check_config:
            raise FileNotFoundError("Config File Missing Required Backend Details!")

    for file in all_files:
        file_details.check_file_size(file)
        aws_details.upload_to_aws(file)
