# fasterrcnn_pytorch_api

[![Build Status](https://jenkins.indigo-datacloud.eu/buildStatus/icon?job=Pipeline-as-code/DEEP-OC-org/UC--fasterrcnn_pytorch_api/master)](https://jenkins.indigo-datacloud.eu/job/Pipeline-as-code/job/DEEP-OC-org/job/UC--fasterrcnn_pytorch_api/job/master)

[This external repository](https://github.com/sovit-123/fasterrcnn-pytorch-training-pipeline) provides a pipeline for training PyTorch FasterRCNN models on custom datasets. You can choose between official PyTorch models trained on the COCO dataset or use any backbone from Torchvision classification models, and even define your own custom backbones.

## Training and Inference

To learn how to train and perform inference using this pipeline, please refer to the following links:
- [How to Train Faster RCNN ResNet50 FPN V2 on Custom Dataset?](https://debuggercafe.com/how-to-train-faster-rcnn-resnet50-fpn-v2-on-custom-dataset/#download-code)
- [Small Scale Traffic Light Detection using PyTorch](https://debuggercafe.com/small-scale-traffic-light-detection/)

We have integrated a DeepaaS API for the existing code of this module for object detection using the FasterRCNN model.

More information about the model can be found [here](https://github.com/sovit-123/fasterrcnn-pytorch-training-pipeline).

## Install the API and the external submodule requirement

To launch the API, first, install the package, and then run [DeepaaS](https://github.com/indigo-dc/DEEPaaS):

```bash
git clone --depth 1 https://github.com/falibabaei/fasterrcnn_pytorch_api
cd fasterrcnn_pytorch_api
git submodule init
git submodule update
pip install -e ./path/to/submodule/dir
pip install -e .
```

The associated Docker container for this module can be found at: https://git.scc.kit.edu/m-team/ai/DEEP-OC-fasterrcnn_pytorch_api.git

## Project Structure

```
├── LICENSE                <- License file
│
├── README.md              <- The top-level README for developers using this project.
│
├── requirements.txt       <- The requirements file for reproducing the analysis environment, e.g., generated with `pip freeze > requirements.txt`
│
├── setup.py, setup.cfg    <- Makes the project pip installable (`pip install -e .`) so that fasterrcnn_pytorch_api can be imported
│
├── fasterrcnn_pytorch_api <- Source code for use in this project.
│   ├── config            <- API configuration subpackage
│   ├── scripts           <- API scripts subpackage for predictions and training the model
│   ├── __init__.py       <- File for initializing the python library
│   ├── api.py            <- API core module for endpoint methods
│   ├── fields.py         <- API core fields for arguments
│   └── utils_api.py      <- API utilities module
│
├── Jenkinsfile           <- Describes the basic Jenkins CI/CD pipeline
├── data                  <- Folder to store data for training and prediction
└── models                <- Folder to store checkpoints
```

## Dataset Preparation

The dataset should be in coco format (.xml). Put your data in the data directory with the following structure:
```
data
	├── train_imgs
	├── train_labels
	├── valid_imgs
	└── valid_labels
	└── config.yaml
```

The `config.yaml` file contains the following information about the data:

```yaml
# Images and labels directory should be relative to train.py
TRAIN_DIR_IMAGES: '../data/train_imgs'
TRAIN_DIR_LABELS: '../data/train_labels'
VALID_DIR_IMAGES: '../data/valid_imgs'
VALID_DIR_LABELS: '../data/valid_labels'
# Class names.
CLASSES: [
    class1, class2, ...
]
# Number of classes.
NC: 2
```

## Launching the API

To train the model, run:
```
deepaas-run --listen-ip 0.0.0.0
```
Then, open the Swagger interface, change the hyperparameters in the train section, and click on train.
