from setuptools import setup, find_packages

setup(
    name='aurora-btc-engine',
    version='1.0.0',
    packages=find_packages(),
    install_requires=[
        'python-dotenv==1.0.1',
        'websockets==12.0',
        'aiohttp==3.9.5',
        'pandas==2.2.2',
        'numpy==1.26.4',
        'ccxt==4.4.36',
        'scipy==1.13.1',
        'asyncio-mqtt==0.18.6',
    ],
    entry_points={
        'console_scripts': [
            'aurora=aurora.main:main',
        ],
    },
)
