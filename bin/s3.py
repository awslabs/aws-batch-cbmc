# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
A collection of methods for interacting with AWS S3.
"""

import subprocess
import os
import re
import sys
import errno
from pprint import pprint

import boto3
from botocore.exceptions import ClientError
from botocore.exceptions import WaiterError

import clienterror

################################################################

class S3Exception(Exception):
    """Exception thrown by S3 methods."""

    def __init__(self, msg):
        super(S3Exception, self).__init__()
        self.message = msg

    def __str__(self):
        return self.message

    def __repr__(self):
        return self.message

################################################################

DEBUGGING = True

def abort(msg1, msg2=None, data=None, verbose=False):
    """Abort an S3 method with debugging information."""
    code = clienterror.code(data)
    msgs = [msg1]
    if code is not None:
        msgs.append(" ({})".format(code))
    if msg2 is not None:
        msgs.append(": {}".format(msg2))
    msg = ''.join(msgs)
    if verbose or DEBUGGING:
        print("S3 Exception: {}".format(msg))
        pprint(clienterror.response(data) or data)
    raise S3Exception(msg)

################################################################
# Methods for names and urls of buckets and objects.
#
# A path is the name or url of a bucket or object.
# An "X name" is the name of X stripped of the url prefix s3://
# An "X url" is the url of X with the url prefix s3://
# An object name has two parts: a bucket name and a key

BUCKET_NAME_REGEXP = '[a-z0-9][a-z0-9_-]*'
KEY_WORD_REGEXP = '[a-z0-9][a-z0-9_.-]*'
KEY_NAME_REGEXP = '{key}(/{key})*'.format(key=KEY_WORD_REGEXP)
PATH_REGEXP = '^(s3://)?({})(/({}))?/?(?i)$'.format(BUCKET_NAME_REGEXP,
                                                    KEY_NAME_REGEXP)
BUCKET_NAME_GROUP = 2
KEY_NAME_GROUP = 4

def parse_path(path):
    """Parse a path for an S3 bucket or object for a bucket and a key.

    A path is the name or the url of a bucket or a key.  A path name
    is a path without s3:// and a path url is a path with s3://.

    """
    path = path.strip()
    match = re.match(PATH_REGEXP, path)
    if match is None:
        return None
    bkt = match.group(BUCKET_NAME_GROUP)
    key = match.group(KEY_NAME_GROUP)
    return (bkt, key)

def is_path(path):
    """The path is a valid path for an S3 bucket or object."""
    pair = parse_path(path)
    return pair is not None

def is_bucket(path):
    """The path is a valid path for an S3 bucket."""
    pair = parse_path(path)
    if pair is None:
        return False
    (bkt, key) = pair
    return bkt is not None and key is None

def is_object(path):
    """The path is a valid path for an S3 object."""
    pair = parse_path(path)
    if pair is None:
        return False
    (bkt, key) = pair
    return bkt is not None and key is not None

def path_name(path):
    """Extract a path name from a path."""
    pair = parse_path(path)
    if pair is None:
        return None
    (bkt, key) = pair
    if key is None:
        return '{}'.format(bkt)
    return '{}/{}'.format(bkt, key)

def bucket_name(path):
    """Extract a bucket name from a path."""
    pair = parse_path(path)
    if pair is None:
        return None
    (bkt, _) = pair
    return bkt

def key_name(path):
    """Extract an object key name from a path."""
    pair = parse_path(path)
    if pair is None:
        return None
    (_, key) = pair
    return key

def path_url(path):
    """Form the url for a bucket or object given by a path."""
    name = path_name(path)
    if name is None:
        return None
    return 's3://{}'.format(name)

def bucket_url(path):
    """Form the url for a bucket given by a path."""
    if not is_bucket(path):
        return None
    return path_url(path)

def object_url(path):
    """Form the url for an object given by a path."""
    if not is_object(path):
        return None
    return path_url(path)

################################################################
# Testing for existence

def path_exists(path, client=None, region=None):
    """Test that path names an object and the object exists."""
    if is_bucket(path):
        return bucket_exists(path, client, region)
    if is_object(path):
        return object_exists(path, client, region)
    return False

def bucket_exists(path, client=None, region=None):
    """Test that path names a bucket and the bucket exists"""

    if client is None:
        client = boto3.client('s3', region_name=region)

    if not is_bucket(path):
        return False
    bkt = bucket_name(path)

    try:
        client.head_bucket(Bucket=bkt)
    except ClientError as exc:
        if clienterror.is_not_found(exc):
            return False
        if clienterror.is_forbidden(exc):
            return False
        abort("Error testing bucket existence", path, data=exc)
    return True

def object_exists(path, client=None, region=None):
    """Test that path names an object and the object exists"""

    if client is None:
        client = boto3.client('s3', region_name=region)

    if not is_object(path):
        return False
    bucket = bucket_name(path)
    key = key_name(path)

    try:
        response = client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if clienterror.is_not_found(exc):
            return False
        if clienterror.is_forbidden(exc):
            return False
        abort("Error testing object existence", path, data=exc)
    if not response.get('ETag', False):
        return False
    return True

################################################################
# Creation
#
# Creating and deleting objects and buckets rapidly may have race conditions

def create_path(path, client=None, region=None, force=False):
    """Create a bucket or object."""
    if is_bucket(path):
        create_bucket(path, client=client, region=region)
        return
    if is_object(path):
        create_object(path, client=client, region=region, force=force)
        return
    if force:
        return
    abort("Error creating path", path)

def create_bucket(path, quiet=True, client=None, region=None):
    """Create a bucket"""

    if client is None:
        client = boto3.client('s3', region_name=region)

    if not is_bucket(path):
        abort("Not a bucket", path)
    bkt = bucket_name(path)

    try:
        client.create_bucket(Bucket=bkt)
    except ClientError as exc:
        if not clienterror.is_bucketalreadyexists(exc):
            abort("Error creating bucket", path, data=exc, verbose=not quiet)

def create_object(path, client=None, region=None, force=False):
    """Create an object"""

    if client is None:
        client = boto3.client('s3', region_name=region)

    if not is_object(path):
        abort("Not an object name", path)
    bucket = bucket_name(path)
    key = key_name(path)

    if force:
        create_bucket(bucket, client=client, region=region)

    try:
        response = client.put_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        # Creating an object that already exists generates no error
        abort("Error creating object", key, data=exc)
    if not response.get('ETag', False):
        abort("Error creating object", key, data=response)

def copy_file_to_object(filename, path, client=None, region=None):
    """Copy local file to an S3 object"""

    if client is None:
        client = boto3.client('s3', region_name=region)

    if not is_object(path):
        abort("Not an object name", path)
    bucket = bucket_name(path)
    key = key_name(path)

    try:
        client.upload_file(filename, bucket, key)
    except ClientError as exc:
        abort("Error copying file to object: {}, {}".format(filename, path),
              "", data=exc)

def copy_object_to_file(objectname, filename, client=None, region=None):
    """Copy an S3 object to a local file"""

    if client is None:
        client = boto3.client('s3', region_name=region)

    if not is_object(objectname):
        abort("Not an object name", objectname)
    bucket = bucket_name(objectname)
    key = key_name(objectname)

    try:
        client.download_file(bucket, key, filename)
    except ClientError as exc:
        abort("Error copying object {} to file {}".format(objectname, filename),
              "", data=exc)

################################################################
# Deletion
#
#
# Creating and deleting objects and buckets rapidly may have race conditions

def delete_path(path, recursive=False, client=None, region=None,
                quiet=True, force=False):
    """Delete a bucket or object."""
    # pylint: disable=too-many-arguments

    if is_bucket(path):
        delete_bucket(path, recursive=recursive, client=client, region=region,
                      quiet=quiet, force=force)
        return
    if is_object(path):
        delete_object(path, recursive=recursive, client=client, region=region,
                      quiet=quiet, force=force)
        return
    if force:
        return
    abort("Error deleting path", path)

def delete_bucket(path, recursive=False, client=None, region=None,
                  quiet=True, force=False):
    """Delete a bucket (recursive => and everything in it)"""
    # pylint: disable=too-many-arguments

    if client is None:
        client = boto3.client('s3', region_name=region)

    if not is_bucket(path):
        if force:
            return
        abort("Not a bucket", path)
    bkt = bucket_name(path)

    if recursive:
        delete_object(
            bkt, recursive=recursive, client=client, region=region,
            quiet=quiet)

    try:
        client.delete_bucket(Bucket=bkt)
    except ClientError as exc:
        if not clienterror.is_nosuchbucket(exc):
            abort("Error deleting bucket", path, data=exc, verbose=not quiet)

def delete_object(path, recursive=False, client=None, region=None,
                  quiet=True, force=False):
    """Delete an object (recursive => and everything underneath it)"""
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-branches

    if client is None:
        client = boto3.client('s3', region_name=region)

    if not is_path(path):  # not "is_object(path)" for recursive to work !!!
        if force:
            return
        abort("Not an object name", path)
    bucket = bucket_name(path)
    prefix = key_name(path) or ""

    if not bucket_exists(bucket, client, region):
        if force:
            return
        abort("No such bucket", path)

    if recursive:
        while True:
            try:
                response = client.list_objects(Bucket=bucket, Prefix=prefix)
            except ClientError as exc:
                # not to fail here can induce an infinite loop
                abort("Error deleting objects", path,
                      data=exc, verbose=not quiet)

            objects = response.get('Contents', None)
            if objects is None:
                break

            for obj in objects:
                key = obj.get('Key', None)
                if key is None:
                    # not to fail here can induce an infinite loop
                    abort("Error deleting objects", path, data=obj,
                          verbose=not quiet)
                if not quiet:
                    print("Deleting object {}".format(key))
                try:
                    client.delete_object(Bucket=bucket, Key=key)
                except ClientError as exc:
                    # deleting a nonexistent object does not generate an error
                    abort("Error deleting object", key,
                          data=exc, verbose=not quiet)
    else:
        try:
            response = client.delete_object(Bucket=bucket, Key=prefix)
        except ClientError as exc:
            # deleting a nonexistent object does not generate an error
            abort("Error deleting object", key, data=exc, verbose=not quiet)

################################################################
# Synchronization

INTERVAL = 5
ATTEMPTS = 200

def wait_for_path(path, client=None, region=None,
                  interval=INTERVAL, attempts=ATTEMPTS):
    """Wait for a bucket or object to exist."""

    if is_bucket(path):
        wait_for_bucket(path, client, region, interval, attempts)
        return
    if is_object(path):
        wait_for_object(path, client, region, interval, attempts)
        return
    abort("Failed to wait for bucket or object: {}".format(path))

def wait_for_bucket(path, client=None, region=None,
                    interval=INTERVAL, attempts=ATTEMPTS):
    """Wait for bucket to exist."""

    wait_for_bucket_condition(
        path, 'bucket_exists', client, region, interval, attempts)

def wait_for_object(path, client=None, region=None,
                    interval=INTERVAL, attempts=ATTEMPTS):
    """Wait for object to exist."""

    wait_for_object_condition(
        path, 'object_exists', client, region, interval, attempts)

def wait_for_no_path(path, client=None, region=None,
                     interval=INTERVAL, attempts=ATTEMPTS):
    """Wait for a bucket or object to no longer exist."""

    if is_bucket(path):
        wait_for_no_bucket(path, client, region, interval, attempts)
        return
    if is_object(path):
        wait_for_no_object(path, client, region, interval, attempts)
        return
    abort("Failed to wait for bucket or object: {}".format(path))

def wait_for_no_bucket(path, client=None, region=None,
                       interval=INTERVAL, attempts=ATTEMPTS):
    """Wait for bucket to no longer exist."""

    wait_for_bucket_condition(path, 'bucket_not_exists',
                              client, region, interval, attempts)

def wait_for_no_object(path, client=None, region=None,
                       interval=INTERVAL, attempts=ATTEMPTS):
    """Wait for object to no longer exist."""

    wait_for_object_condition(path, 'object_not_exists',
                              client, region, interval, attempts)

def wait_for_bucket_condition(path, condition, client=None, region=None,
                              interval=INTERVAL, attempts=ATTEMPTS):
    """Wait for a condition to be true of a bucket."""
    # pylint: disable=too-many-arguments

    if client is None:
        client = boto3.client('s3', region_name=region)

    if not is_bucket(path):
        return
    bkt = bucket_name(path)

    try:
        waiter = client.get_waiter(condition)
    except ClientError as exc:
        abort("Failed to wait for bucket: {} {}".format(condition, path),
              data=exc)

    try:
        config = {"Delay": interval, "MaxAttempts": attempts}
        waiter.wait(Bucket=bkt, WaiterConfig=config)
    except ClientError as exc:
        abort("Failed to wait for bucket: {} {}".format(condition, path),
              data=exc)
    except WaiterError as exc:
        abort("Wait for condition timed out: {} {}"
              .format(condition, path),
              data=exc)

def wait_for_object_condition(path, condition, client=None, region=None,
                              interval=INTERVAL, attempts=ATTEMPTS):
    """Wait for a condition to be true of an object."""
    # pylint: disable=too-many-arguments

    if client is None:
        client = boto3.client('s3', region_name=region)

    if not is_object(path):
        return
    bkt = bucket_name(path)
    key = key_name(path)

    try:
        waiter = client.get_waiter(condition)
    except ClientError as exc:
        abort("Failed to wait for object: {} {}".format(condition, path),
              data=exc)

    try:
        config = {"Delay": interval, "MaxAttempts": attempts}
        waiter.wait(Bucket=bkt, Key=key, WaiterConfig=config)
    except ClientError as exc:
        abort("Failed to wait for object: {} {}".format(condition, path),
              data=exc)

################################################################

# boto3 api omits a sync which is just too useful not to use

def sync_directory_to_bucket(directory, bucket, quiet=False, delete=False, metadata=None):
    """Synchronize a directory to a path (a bucket or bucket and prefix)."""

    if not os.path.isdir(directory):
        abort("Directory does not exist", directory)

    url = path_url(bucket)
    if url is None:
        abort("Not a bucket", bucket)

    try:
        cmd = ['aws', '--debug', 's3', 'sync', directory, url]
        if delete:
            cmd.append('--delete')
        if quiet:
            cmd.append('--quiet')
        if metadata:
            cmd.append('--metadata')
            param_str = ""
            for k in metadata:
                param_str += '{}={},'.format(k, metadata[k])
            param_str = param_str.rstrip(",")
            cmd.append(param_str)
        if not quiet:
            print("Copying directory {} to bucket {}".format(directory, url))
            print("Running copy command: {}".format(cmd))
        sys.stdout.flush()
        subprocess.check_call(cmd)
    except Exception as exc:
        sys.stdout.flush()
        print("Error copying directory {} to bucket {} ({})"
              .format(directory, url, exc))
        sys.stdout.flush()
        raise exc

def sync_bucket_to_directory(bucket, directory, quiet=False, delete=False):
    """Synchronize a path (a bucket or bucket and prefix) to a directory."""

    try:
        os.makedirs(directory)
    except OSError as exc:
        if not (exc.errno == errno.EEXIST and os.path.isdir(directory)):
            abort("Error creating directory", directory)

    url = path_url(bucket)
    if url is None:
        abort("Not a bucket", bucket)

    try:
        cmd = ['aws', '--debug', 's3', 'sync', url, directory]
        if delete:
            cmd.append('--delete')
        if quiet:
            cmd.append('--quiet')
        if not quiet:
            print("Copying bucket {} to directory {}".format(url, directory))
        sys.stdout.flush()
        subprocess.check_call(cmd)
    except Exception as exc:
        sys.stdout.flush()
        print("Error copying bucket {} to directory {} ({})"
              .format(url, directory, exc))
        sys.stdout.flush()
        raise exc

################################################################

# The response never seems to have the documented 'Status' key ???

def versioning_enabled(bucket, client=None, region=None):
    """Object versioning is enabled in the S3 bucket."""
    if client is None:
        client = boto3.client('s3', region_name=region)

    bucket = bucket.strip()
    if not is_bucket(bucket):
        return False

    try:
        response = client.get_bucket_versioning(Bucket=bucket)
    except ClientError:
        return False

    status = response.get('Status', 'Suspended')
    return status == 'Enabled'

################################################################
