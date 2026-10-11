from setuptools import setup

setup(name="robotx_ocs_protocol", version="0.1.0", packages=["OCS"], package_dir={"OCS": "."},
      data_files=[("share/ament_index/resource_index/packages", ["resource/robotx_ocs_protocol"]),
                  ("share/robotx_ocs_protocol", ["package.xml"])], install_requires=["setuptools"],
      tests_require=["pytest"], test_suite="pytest")
