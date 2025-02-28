import json
from unittest.mock import mock_open
from unittest.mock import patch

import boto3
import pytest
from botocore.stub import Stubber
from click.testing import CliRunner
from moto import mock_ec2
from moto import mock_ecs
from moto import mock_elbv2

from commands.dns_cli import add_records
from commands.dns_cli import assign_domain
from commands.dns_cli import check_domain
from commands.dns_cli import check_for_records
from commands.dns_cli import check_r53
from commands.dns_cli import create_cert
from commands.dns_cli import create_hosted_zone
from commands.dns_cli import get_load_balancer_domain_and_configuration

HYPHENATED_APPLICATION_NAME = "hyphenated-application-name"
ALPHANUMERIC_ENVIRONMENT_NAME = "alphanumericenvironmentname123"
ALPHANUMERIC_SERVICE_NAME = "alphanumericservicename123"
COPILOT_IDENTIFIER = "c0PIlotiD3ntIF3r"
CLUSTER_NAME_SUFFIX = f"Cluster-{COPILOT_IDENTIFIER}"
SERVICE_NAME_SUFFIX = f"Service-{COPILOT_IDENTIFIER}"


# Not much value in testing these while moto doesn't support `describe_certificate`, `list_certificates`
def test_wait_for_certificate_validation():
    ...


def test_check_for_records(route53_session):
    response = route53_session.create_hosted_zone(Name="1234", CallerReference="1234")
    assert (
        check_for_records(
            route53_session, response["HostedZone"]["Id"], "test.1234", response["HostedZone"]["Id"]
        )
        == True
    )


@patch(
    "commands.dns_cli.wait_for_certificate_validation",
    return_value="arn:1234",
)
@patch("click.confirm")
def test_create_cert(wait_for_certificate_validation, mock_click, acm_session, route53_session):
    stubber = Stubber(acm_session)
    route53_session.create_hosted_zone(Name="1234", CallerReference="1234")

    response_desc = {
        "Certificate": {
            "CertificateArn": "arn:1234567890123456789",
            "DomainName": "test.domain",
            "DomainValidationOptions": [
                {
                    "DomainName": "test.domain",
                    "ValidationStatus": "SUCCESS",
                    "ResourceRecord": {
                        "Name": "test.record",
                        "Type": "CNAME",
                        "Value": "pointing.to.this",
                    },
                    "ValidationMethod": "DNS",
                },
            ],
        }
    }
    expected_params = {"CertificateArn": "arn:1234567890123456789"}

    stubber.add_response("describe_certificate", response_desc, expected_params)
    with stubber:
        acm_session.describe_certificate(CertificateArn="arn:1234567890123456789")

    assert create_cert(acm_session, route53_session, "test.1234", 1).startswith("arn:aws:acm:")


def test_add_records(route53_session):
    response = route53_session.create_hosted_zone(Name="1234", CallerReference="1234")

    route53_session.change_resource_record_sets(
        HostedZoneId=response["HostedZone"]["Id"],
        ChangeBatch={
            "Comment": "test",
            "Changes": [
                {
                    "Action": "CREATE",
                    "ResourceRecordSet": {
                        "Name": "test.1234",
                        "Type": "A",
                        "ResourceRecords": [
                            {
                                "Value": "192.0.2.45",
                            },
                        ],
                        "TTL": 60,
                    },
                }
            ],
        },
    )

    record = {
        "Name": "test.1234",
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [{"Value": "recod.stuff"}],
    }

    assert add_records(route53_session, record, response["HostedZone"]["Id"], "CREATE") == "INSYNC"


@patch("click.confirm")
def test_create_hosted_zone(mock_click, route53_session):
    route53_session.create_hosted_zone(Name="1234", CallerReference="1234")

    assert create_hosted_zone(route53_session, "test.test.1234", "test.1234", 1)


# Listcertificates is not implementaed in moto acm. Neeed to patch it
@patch(
    "commands.dns_cli.create_cert",
    return_value="arn:1234",
)
def test_check_r53(create_cert, route53_session):
    session = boto3.session.Session(profile_name="foo")
    route53_session.create_hosted_zone(Name="test.1234", CallerReference="1234")

    assert check_r53(session, session, "test.test.1234", "test.1234") == "arn:1234"


@patch(
    "commands.dns_cli.check_aws_conn",
)
@patch(
    "commands.dns_cli.check_r53",
    return_value="arn:1234",
)
def test_check_domain(check_aws_conn, check_r53, fakefs):
    fakefs.create_file(
        "copilot/manifest.yml",
        contents="""
environments:
  dev:
    http:
      alias: v2.app.dev.test.1234

  staging:
    http:
      alias: v2.app.staging.test.12345
""",
    )

    runner = CliRunner()
    result = runner.invoke(
        check_domain,
        ["--domain-profile", "foo", "--project-profile", "foo", "--base-domain", "test.1234"],
    )
    expected = "Checking file: copilot/manifest.yml\nDomains listed in manifest file\n\nEnvironment: dev => Domain: v2.app.dev.test.1234\n\nEnvironment: staging => Domain: v2.app.staging.test.12345\n\nHere are your Certificate ARNs:\nDomain: v2.app.dev.test.1234\t => Cert ARN: arn:1234\nDomain: v2.app.staging.test.12345\t => Cert ARN: arn:1234\n"

    assert result.output == expected


@patch(
    "commands.dns_cli.check_aws_conn",
)
@patch(
    "commands.dns_cli.check_r53",
    return_value="arn:1234",
)
def test_check_domain_env_flag(check_aws_conn, check_r53, fakefs):
    fakefs.create_file(
        "copilot/manifest.yml",
        contents="""
environments:
  dev:
    http:
      alias: v2.app.dev.test.1234

  staging:
    http:
      alias: v2.app.staging.test.12345
""",
    )

    runner = CliRunner()
    result = runner.invoke(
        check_domain,
        [
            "--domain-profile",
            "foo",
            "--project-profile",
            "foo",
            "--base-domain",
            "test.1234",
            "--env",
            "dev",
        ],
    )

    expected = "Checking file: copilot/manifest.yml\nDomains listed in manifest file\n\nEnvironment: dev => Domain: v2.app.dev.test.1234\n\nHere are your Certificate ARNs:\nDomain: v2.app.dev.test.1234\t => Cert ARN: arn:1234\n"

    assert result.output == expected


@patch(
    "commands.dns_cli.check_aws_conn",
)
@patch("commands.dns_cli.check_response", return_value="{}")
@patch(
    "commands.dns_cli.ensure_cwd_is_repo_root",
)
def test_assign_domain(check_aws_conn, check_response, ensure_cwd_is_repo_root):
    runner = CliRunner()
    result = runner.invoke(
        assign_domain,
        [
            "--app",
            "some-app",
            "--domain-profile",
            "foo",
            "--project-profile",
            "foo",
            "--svc",
            "web",
            "--env",
            "dev",
        ],
    )
    assert result.output.startswith("There are no clusters matching")


@mock_ecs
def test_get_load_balancer_domain_and_configuration_no_clusters(capfd):
    with pytest.raises(SystemExit):
        get_load_balancer_domain_and_configuration(
            boto3.Session(),
            HYPHENATED_APPLICATION_NAME,
            ALPHANUMERIC_ENVIRONMENT_NAME,
            ALPHANUMERIC_SERVICE_NAME,
        )

    out, _ = capfd.readouterr()

    assert (
        out == f"There are no clusters matching {HYPHENATED_APPLICATION_NAME} in this aws account\n"
    )


@mock_ecs
def test_get_load_balancer_domain_and_configuration_no_services(capfd):
    boto3.Session().client("ecs").create_cluster(
        clusterName=f"{HYPHENATED_APPLICATION_NAME}-{ALPHANUMERIC_ENVIRONMENT_NAME}-{CLUSTER_NAME_SUFFIX}"
    )
    with pytest.raises(SystemExit):
        get_load_balancer_domain_and_configuration(
            boto3.Session(),
            HYPHENATED_APPLICATION_NAME,
            ALPHANUMERIC_SERVICE_NAME,
            ALPHANUMERIC_ENVIRONMENT_NAME,
        )

    out, _ = capfd.readouterr()

    assert (
        out == f"There are no services matching {ALPHANUMERIC_SERVICE_NAME} in this aws account\n"
    )


@mock_elbv2
@mock_ec2
@mock_ecs
def test_get_load_balancer_domain_and_configuration(tmp_path):
    cluster_name = (
        f"{HYPHENATED_APPLICATION_NAME}-{ALPHANUMERIC_ENVIRONMENT_NAME}-{CLUSTER_NAME_SUFFIX}"
    )
    service_name = f"{HYPHENATED_APPLICATION_NAME}-{ALPHANUMERIC_ENVIRONMENT_NAME}-{ALPHANUMERIC_SERVICE_NAME}-{SERVICE_NAME_SUFFIX}"
    session = boto3.Session()
    mocked_vpc_id = session.client("ec2").create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    mocked_subnet_id = session.client("ec2").create_subnet(
        VpcId=mocked_vpc_id, CidrBlock="10.0.0.0/16"
    )["Subnet"]["SubnetId"]
    mocked_elbv2_client = session.client("elbv2")
    mocked_load_balancer_arn = mocked_elbv2_client.create_load_balancer(
        Name="foo", Subnets=[mocked_subnet_id]
    )["LoadBalancers"][0]["LoadBalancerArn"]
    target_group_arn = mocked_elbv2_client.create_target_group(Name="foo")["TargetGroups"][0][
        "TargetGroupArn"
    ]
    mocked_elbv2_client.create_listener(
        LoadBalancerArn=mocked_load_balancer_arn,
        DefaultActions=[{"Type": "forward", "TargetGroupArn": target_group_arn}],
    )
    mocked_ecs_client = session.client("ecs")
    mocked_ecs_client.create_cluster(clusterName=cluster_name)
    mocked_ecs_client.create_service(
        cluster=cluster_name,
        serviceName=service_name,
        loadBalancers=[{"loadBalancerName": "foo", "targetGroupArn": target_group_arn}],
    )
    mocked_service_manifest_contents = {
        "environments": {ALPHANUMERIC_ENVIRONMENT_NAME: {"http": {"alias": "somedomain.tld"}}}
    }
    open_mock = mock_open(read_data=json.dumps(mocked_service_manifest_contents))

    with patch("commands.dns_cli.open", open_mock):
        domain_name, load_balancer_configuration = get_load_balancer_domain_and_configuration(
            boto3.Session(),
            HYPHENATED_APPLICATION_NAME,
            ALPHANUMERIC_SERVICE_NAME,
            ALPHANUMERIC_ENVIRONMENT_NAME,
        )

    open_mock.assert_called_once_with(f"./copilot/{ALPHANUMERIC_SERVICE_NAME}/manifest.yml", "r")
    assert domain_name == "somedomain.tld"
    assert load_balancer_configuration["LoadBalancerArn"] == mocked_load_balancer_arn
    assert load_balancer_configuration["LoadBalancerName"] == "foo"
    assert load_balancer_configuration["VpcId"] == mocked_vpc_id
    assert load_balancer_configuration["AvailabilityZones"][0]["SubnetId"] == mocked_subnet_id
