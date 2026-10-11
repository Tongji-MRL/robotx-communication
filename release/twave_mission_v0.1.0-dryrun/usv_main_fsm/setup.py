from setuptools import setup


setup(
    name="usv_main_fsm",
    version="0.1.0",
    packages=["usv_main_fsm"],
    package_dir={"usv_main_fsm": "."},
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/usv_main_fsm"]),
        ("share/usv_main_fsm", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    tests_require=["pytest"],
    test_suite="pytest",
    zip_safe=True,
)
