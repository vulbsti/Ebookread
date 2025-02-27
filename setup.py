from setuptools import setup, find_packages

setup(
    name="epubread",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "PyQt5>=5.15.0",
        "ebooklib>=0.17.0",
        "Pillow>=8.0.0",
        "lxml>=4.6.0",
        "pdfminer.six>=20200517",
        "mobi>=0.3.0",
        "fb2reader>=0.0.9",
    ],
    entry_points={
        "console_scripts": [
            "epubread=epubread.main:main",
        ],
    },
    author="EPUBRead Team",
    author_email="info@epubread.com",
    description="A lightweight ebook reader for Ubuntu/Debian",
    keywords="epub, ebook, reader, pdf, mobi, fb2",
    url="https://github.com/epubread/epubread",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Office/Business",
    ],
)