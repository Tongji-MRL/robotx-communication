from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(package="twave_mission_dryrun", executable="mission_coordinator_node", name="twave_mission_coordinator_dryrun", parameters=[{"dry_run": True}]),
        Node(package="twave_mission_dryrun", executable="fake_usv_executor", name="fake_usv_executor_dryrun", parameters=[{"dry_run": True}]),
    ])
