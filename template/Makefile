# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

-include ../Makefile.local

default:
	@echo Nothing to make for Cloud Formation template

install:
	aws cloudformation create-stack \
		--stack-name cbmc \
		--template-body file://cbmc.yaml \
		--capabilities CAPABILITY_IAM \
		--parameters ParameterKey=BuildToolsAccountId,ParameterValue=$(BUILD_TOOLS_AWSID) ParameterKey=MaxVcpus,ParameterValue=$(MAX_VCPUS)

update:
	aws cloudformation update-stack \
		--stack-name cbmc \
		--template-body file://cbmc.yaml \
		--capabilities CAPABILITY_IAM \
		--parameters ParameterKey=BuildToolsAccountId,UsePreviousValue=true ParameterKey=MaxVcpus,UsePreviousValue=true

clean:
	$(RM) *~

.PHONY: default install update clean

