import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_iam as iam,
    aws_opensearchserverless as aws_opss,
    Duration,
    BundlingOptions,
    CfnOutput,
    Fn,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    RemovalPolicy,
)
from constructs import Construct
from pathlib import Path
import yaml
import json
import uuid

CONFIG_PATH = "../config.yaml"
config = yaml.safe_load(open(CONFIG_PATH))


class RagBackendStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        #################################################################################
        # CDK FOR ASSETS INPUT BUCKET
        #################################################################################

        bucket = s3.Bucket(
            self,
            "RAGDataBucket",
            bucket_name=f"{config['input_bucket_name']}-{uuid.uuid4().hex[:8]}",  # Specify your bucket name
            removal_policy=RemovalPolicy.RETAIN,  # RETAIN to prevent accidental deletion
            auto_delete_objects=False,
            versioned=True,  # Enable versioning
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,  # Block public access
        )

        #################################################################################
        # CDK FOR THE OPENSEARCH VECTOR DATABASE
        #################################################################################
        collection_name = config["opensearch_collection_name"]

        network_security_policy = json.dumps(
            [
                {
                    "Rules": [
                        {
                            "Resource": [f"collection/{collection_name}"],
                            "ResourceType": "dashboard",
                        },
                        {
                            "Resource": [f"collection/{collection_name}"],
                            "ResourceType": "collection",
                        },
                    ],
                    "AllowFromPublic": True,
                }
            ],
            indent=2,
        )

        cfn_network_security_policy = aws_opss.CfnSecurityPolicy(
            self,
            "NetworkSecurityPolicy",
            policy=network_security_policy,
            name=f"{collection_name}-security-policy",
            type="network",
        )

        encryption_security_policy = json.dumps(
            {
                "Rules": [
                    {
                        "Resource": [f"collection/{collection_name}"],
                        "ResourceType": "collection",
                    }
                ],
                "AWSOwnedKey": True,
            },
            indent=2,
        )

        cfn_encryption_security_policy = aws_opss.CfnSecurityPolicy(
            self,
            "EncryptionSecurityPolicy",
            policy=encryption_security_policy,
            name=f"{collection_name}-security-policy",
            type="encryption",
        )

        cfn_collection = aws_opss.CfnCollection(
            self,
            collection_name,
            name=collection_name,
            description="Collection to be used for vector analysis using OpenSearch Serverless",
            type="VECTORSEARCH",  # [SEARCH, TIMESERIES]
        )
        cfn_collection.add_dependency(cfn_network_security_policy)
        cfn_collection.add_dependency(cfn_encryption_security_policy)

        data_access_policy = json.dumps(
            [
                {
                    "Rules": [
                        {
                            "Resource": [f"collection/{collection_name}"],
                            "Permission": [
                                "aoss:CreateCollectionItems",
                                "aoss:DeleteCollectionItems",
                                "aoss:UpdateCollectionItems",
                                "aoss:DescribeCollectionItems",
                            ],
                            "ResourceType": "collection",
                        },
                        {
                            "Resource": [f"index/{collection_name}/*"],
                            "Permission": [
                                "aoss:CreateIndex",
                                "aoss:DeleteIndex",
                                "aoss:UpdateIndex",
                                "aoss:DescribeIndex",
                                "aoss:ReadDocument",
                                "aoss:WriteDocument",
                            ],
                            "ResourceType": "index",
                        },
                    ],
                    "Principal": [
                        f"arn:aws:iam::{Stack.of(self).account}:root"  # Grant access to the AWS account
                    ],
                    "Description": "data-access-rule",
                }
            ],
            indent=2,
        )

        data_access_policy_name = f"{collection_name}-policy"
        assert len(data_access_policy_name) <= 32

        cfn_access_policy = aws_opss.CfnAccessPolicy(
            self,
            "OpssDataAccessPolicy",
            name=data_access_policy_name,
            description="Policy for data access",
            policy=data_access_policy,
            type="data",
        )


        # Removes https:// from Opensearch endpoint
        opensearch_endpoint = Fn.select(
            1, Fn.split("https://", cfn_collection.attr_collection_endpoint)
        )

        collection_arn = cfn_collection.attr_arn

        #################################################################################
        # CDK FOR THE LAMBDA WHICH INGESTS DOCUMENTS
        #################################################################################

        ingest_function = _lambda.Function(
            self,
            "IngestLambdaFunction",
            code=_lambda.Code.from_asset(
                "../infra/lambda_ingest",
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            ),
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="document_pipeline.lambda_handler",
            memory_size=1024,
            timeout=Duration.minutes(15),
            environment={
                "OPENSEARCH_ENDPOINT": opensearch_endpoint,
                "CHUNK_SIZE": config["chunk_size"],
                "OVERLAP": config["overlap"],
            },
        )

        ingest_function.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3FullAccess")
        )
        ingest_function.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonTextractFullAccess")
        )
        ingest_function.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonBedrockFullAccess")
        )

        # Define custom inline policy
        opensearch_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "aoss:APIAccessAll",
            ],
            resources=["*"],
        )

        # Attach inline policy to the Lambda role
        ingest_function.role.add_to_policy(opensearch_policy)

        #################################################################################
        # CDK FOR THE LAMBDA WHICH SERVES THE API
        #################################################################################

        # Define the Lambda function
        chat_lambda = _lambda.Function(
            self,
            "ChatbotConversationHandler",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset(
                "../infra/backend",
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            ),
            handler="chatbot_backend.lambda_handler",
            timeout=Duration.seconds(60),
            environment={
                "OPENSEARCH_ENDPOINT": opensearch_endpoint,
                "OPENSEARCH_INDEX": config["opensearch_index_name"],
                "CHAT_MODEL_ID": config["model"]["chat"],
                "EMBEDDING_MODEL_ID": config["model"]["embedding"],
                "CHAT_PROMPT": config["chat_prompt"],
            },
        )

        chat_lambda.add_to_role_policy(iam.PolicyStatement(
            actions=["s3:GetObject"],
            resources=[f"arn:aws:s3:::{config['input_bucket_name']}/*"],
            effect=iam.Effect.ALLOW
        ))

        # Attach AWS managed policies
        chat_lambda.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonBedrockFullAccess")
        )
        chat_lambda.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonOpenSearchServiceFullAccess"
            )
        )

        # Define custom inline policy
        opensearch_policy = iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "aoss:APIAccessAll",
            ],
            resources=[collection_arn],
        )

        # Attach inline policy to the Lambda role
        chat_lambda.role.add_to_policy(opensearch_policy)

        #################################################################################
        # CDK FOR API
        #################################################################################
        # Define the API Gateway
        api = apigw.RestApi(
            self,
            "RagAPI",
            rest_api_name="RagChatbotAPI",
            description="API Gateway to be served by a lambda",
        )

        # Create a resource and method
        resource = api.root.add_resource("chat-response")
        integration = apigw.LambdaIntegration(chat_lambda, proxy=True)

        # Add method to the resource
        resource.add_method("POST", integration)

        # Add CORS support
        resource.add_method(
            "OPTIONS",
            apigw.MockIntegration(
                integration_responses=[
                    apigw.IntegrationResponse(
                        status_code="200",
                        response_parameters={
                            "method.response.header.Access-Control-Allow-Headers": "'Content-Type,X-Amz-Date,Authorization,X-Api-Key'",
                            "method.response.header.Access-Control-Allow-Origin": "'*'",
                            "method.response.header.Access-Control-Allow-Methods": "'OPTIONS,POST'",
                        },
                    )
                ],
                request_templates={"application/json": '{"statusCode": 200}'},
            ),
            method_responses=[
                apigw.MethodResponse(
                    status_code="200",
                    response_parameters={
                        "method.response.header.Access-Control-Allow-Headers": True,
                        "method.response.header.Access-Control-Allow-Origin": True,
                        "method.response.header.Access-Control-Allow-Methods": True,
                    },
                )
            ],
        )

        # Create API Key
        api_key = apigw.ApiKey(
            self,
            "RagChatbotApiKey",
            api_key_name="RagChatAPIKey",
            description="API key for accessing RagChatbotAPI",
        )

        # Create Usage Plan and associate with API Key and API Stage
        usage_plan = apigw.UsagePlan(
            self,
            "RagChatUsagePlan",
            name="RagChatUsagePlan",
            throttle=apigw.ThrottleSettings(
                rate_limit=10,
                burst_limit=2,
            ),
            quota=apigw.QuotaSettings(limit=1000, period=apigw.Period.DAY),
        )

        usage_plan.add_api_key(api_key)
        usage_plan.add_api_stage(stage=api.deployment_stage)

        # Output the API URL, API Key, Opensearch endpoint
        CfnOutput(
            self,
            "IngestLambdaFunctionName",
            value=ingest_function.function_name,
            export_name="RagBackendStack-IngestLambdaFunctionName",
        )

        CfnOutput(
            self,
            "OpensearchAPIEndpoint",
            value=opensearch_endpoint,
            export_name="RagBackendStack-OpensearchAPIEndpoint",
        )
