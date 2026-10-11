from setuptools import find_packages, setup


setup(
    name="twave_mission_dryrun",
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/twave_mission_dryrun"]),
        ("share/twave_mission_dryrun", ["package.xml"]),
        ("share/twave_mission_dryrun/launch", ["launch/dry_run.launch.py"]),
    ],
    install_requires=["setuptools", "paho-mqtt==2.0"],
    tests_require=["pytest"],
    test_suite="pytest",
    zip_safe=True,
    entry_points={"console_scripts": [
        "mission_coordinator_node = twave_mission_dryrun.mission_coordinator_node:main",
        "fake_usv_executor = twave_mission_dryrun.fake_usv_executor:main",
        "twave_mqtt_runtime = twave_mission_dryrun.mqtt_runtime_node:main",
    ]},
)
