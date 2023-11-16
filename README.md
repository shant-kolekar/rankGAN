# AMP Sequence Generation with RankGAN

This repository contains the implementation of RankGAN for the generation of antimicrobial peptide (AMP) sequences. The project aims to utilize generative adversarial networks to create novel AMP sequences.

## Prerequisites

It's recommended to set up a virtual environment for this project to avoid conflicts with other packages or Python versions.

Ensure you have __Python 3.6__ installed on your virtual environment. You can download it from [python.org](https://www.python.org/downloads/release/python-360/).

```bash
# Install the required dependencies
pip install -r requirements.txt
```
## Running the Code

To run the code, navigate to the directory where `main.py` is located and run it with the `-d` flag to specify the dataset location. For example:

```bash
python main.py -d 'data/amp.txt'


