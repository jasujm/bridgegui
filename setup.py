from setuptools import setup
setup(
    name="Bridge GUI",
    author="Jaakko Moisio",
    author_email="jaakko@moisio.fi",
    url="https://github.com/jasujm/bridgegui",
    packages=["bridgegui"],
    entry_points={
        "gui_scripts": ["bridgegui=bridgegui.__main__:main"]
    },
    package_data={
        "bridgegui": ["images/*.png"]
    },
    install_requires=["pyzmq>=15.4","PyQt5>=5.7"],
    test_suite="tests",
)
