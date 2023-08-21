from fasterrcnn_pytorch_training_pipeline.torch_utils.engine import (
    train_one_epoch,
    evaluate,
    utils,
)

from fasterrcnn_pytorch_training_pipeline.datasets import (
    create_train_dataset,
    create_valid_dataset,
    create_train_loader,
    create_valid_loader,
)
from fasterrcnn_pytorch_training_pipeline.models.create_fasterrcnn_model import (
    create_model,
)
from fasterrcnn_pytorch_training_pipeline.utils.general import (
    Averager,
    save_model,
    save_model_state,
    SaveBestModel,
    yaml_save,
    init_seeds,
)
from fasterrcnn_pytorch_training_pipeline.utils.logging import (
    set_log,
    set_summary_writer,
    tensorboard_loss_log,
    tensorboard_map_log,
    wandb_log,
    wandb_save_model,
    wandb_init,
)
from torch.utils.data import RandomSampler, SequentialSampler
import torch
import yaml
import numpy as np
import torchinfo
import os


torch.multiprocessing.set_sharing_strategy("file_system")

RANK = int(os.getenv("RANK", -1))

# For same annotation colors each time.
np.random.seed(42)


def main(args):
    # Initialize distributed mode.
    utils.init_distributed_mode(args)
    if not args["disable_wandb"]:
        wandb_init(name=args["name"])

    # Load the data configurations
    with open(args["data_config"]) as file:
        data_configs = yaml.safe_load(file)

    init_seeds(args["seed"] + 1 + RANK, deterministic=True)

    from fasterrcnn_pytorch_api import configs

    # Settings/parameters/constants.
    TRAIN_DIR_IMAGES = os.path.join(
        configs.DATA_PATH, data_configs["TRAIN_DIR_IMAGES"]
    )
    TRAIN_DIR_LABELS = os.path.join(
        configs.DATA_PATH, data_configs["TRAIN_DIR_LABELS"]
    )
    VALID_DIR_IMAGES = os.path.join(
        configs.DATA_PATH, data_configs["VALID_DIR_IMAGES"]
    )
    VALID_DIR_LABELS = os.path.join(
        configs.DATA_PATH, data_configs["VALID_DIR_LABELS"]
    )
    CLASSES = data_configs["CLASSES"]
    NUM_CLASSES = data_configs["NC"]
    NUM_WORKERS = args["workers"]
    if args["device"] and torch.cuda.is_available():
        DEVICE = torch.device("cuda:0")
    else:
        DEVICE = torch.device("cpu")
    print("device", DEVICE)
    NUM_EPOCHS = args["epochs"]
    BATCH_SIZE = args["batch"]
    OUT_DIR = args["name"]
    COLORS = np.random.uniform(0, 1, size=(len(CLASSES), 3))
    # Set logging file.
    set_log(OUT_DIR)
    writer = set_summary_writer(OUT_DIR)

    yaml_save(file_path=os.path.join(OUT_DIR, "opt.yaml"), data=args)

    # Model configurations
    IMAGE_SIZE = args["imgsz"]

    train_dataset = create_train_dataset(
        TRAIN_DIR_IMAGES,
        TRAIN_DIR_LABELS,
        IMAGE_SIZE,
        CLASSES,
        aug_option=args["aug_training_option"],
        use_train_aug=args["use_train_aug"],
        no_mosaic=args["no_mosaic"],
        square_training=args["square_training"],
    )
    valid_dataset = create_valid_dataset(
        VALID_DIR_IMAGES,
        VALID_DIR_LABELS,
        IMAGE_SIZE,
        CLASSES,
        aug_option=args["aug_training_option"],
        square_training=args["square_training"],
    )
    print("Creating data loaders")

    train_sampler = RandomSampler(train_dataset)
    valid_sampler = SequentialSampler(valid_dataset)

    train_loader = create_train_loader(
        train_dataset,
        BATCH_SIZE,
        NUM_WORKERS,
        batch_sampler=train_sampler,
    )
    valid_loader = create_valid_loader(
        valid_dataset,
        BATCH_SIZE,
        NUM_WORKERS,
        batch_sampler=valid_sampler,
    )
    print(f"Number of training samples: {len(train_dataset)}")
    print(f"Number of validation samples: {len(valid_dataset)}\n")

    # Initialize the Averager class.
    train_loss_hist = Averager()
    # Train and validation loss lists to store loss values of all
    # iterations till ena and plot graphs for all iterations.
    train_loss_list = []
    loss_cls_list = []
    loss_box_reg_list = []
    loss_objectness_list = []
    loss_rpn_list = []
    train_loss_list_epoch = []
    val_map_05 = []
    val_map = []
    start_epochs = 0

    if args["weights"] is None:
        print("Building model from scratch...")
        build_model = create_model[args["model"]]
        model = build_model(num_classes=NUM_CLASSES, pretrained=True)

    # Load pretrained weights if path is provided.
    else:
        print("Loading pretrained weights...")

        # Load the pretrained checkpoint.
        checkpoint = torch.load(args["weights"], map_location=DEVICE)
        ckpt_state_dict = checkpoint["model_state_dict"]
        # Get the number of classes from the loaded checkpoint.
        old_classes = ckpt_state_dict[
            "roi_heads.box_predictor.cls_score.weight"
        ].shape[0]

        # Build the new model with number of classes same as checkpoint.
        build_model = create_model[args["model"]]
        model = build_model(num_classes=old_classes)
        # Load weights.
        model.load_state_dict(ckpt_state_dict)

        # Change output features for class predictor and box predictor
        # according to current dataset classes.
        in_features = (
            model.roi_heads.box_predictor.cls_score.in_features
        )
        model.roi_heads.box_predictor.cls_score = torch.nn.Linear(
            in_features=in_features,
            out_features=NUM_CLASSES,
            bias=True,
        )
        model.roi_heads.box_predictor.bbox_pred = torch.nn.Linear(
            in_features=in_features,
            out_features=NUM_CLASSES * 4,
            bias=True,
        )
        # FIXME: should be loaded from the last chaeckpoint or from a timestamp
        if args["resume_training"]:
            print("RESUMING TRAINING FROM LAST CHECKPOINT...")
            # Update the starting epochs, the batch-wise loss list,
            # and the epoch-wise loss list.

            if checkpoint["epoch"]:
                start_epochs = checkpoint["epoch"]
                print(f"Resuming from epoch {start_epochs}...")
                NUM_EPOCHS = start_epochs + NUM_EPOCHS
            if checkpoint["train_loss_list"]:
                print("Loading previous batch wise loss list...")
                train_loss_list = checkpoint["train_loss_list"]
            if checkpoint["train_loss_list_epoch"]:
                print("Loading previous epoch wise loss list...")
                train_loss_list_epoch = checkpoint[
                    "train_loss_list_epoch"
                ]
            if checkpoint["val_map"]:
                print("Loading previous mAP list")
                val_map = checkpoint["val_map"]
            if checkpoint["val_map_05"]:
                val_map_05 = checkpoint["val_map_05"]

    model = model.to(DEVICE)
    if args["distributed"]:
        model = torch.nn.parallel.DistributedDataParallel(
            model, device_ids=[args["gpu"]]
        )
    try:
        torchinfo.summary(
            model,
            device=DEVICE,
            input_size=(BATCH_SIZE, 3, IMAGE_SIZE, IMAGE_SIZE),
        )
    except Exception as e:
        print(f"An error occurred while summarizing the model: {e}")
    # Total parameters and trainable parameters.
    total_params = sum(p.numel() for p in model.parameters())
    print(f"{total_params:,} total parameters.")
    total_trainable_params = sum(
        p.numel() for p in model.parameters() if p.requires_grad
    )
    print(f"{total_trainable_params:,} training parameters.")
    # Get the model parameters.
    params = [p for p in model.parameters() if p.requires_grad]
    # Define the optimizer.
    optimizer = torch.optim.SGD(
        params, lr=args["lr"], momentum=0.9, nesterov=True
    )
    # optimizer = torch.optim.AdamW(params, lr=0.0001, weight_decay=0.0005)
    if args["resume_training"]:
        # LOAD THE OPTIMIZER STATE DICTIONARY FROM THE CHECKPOINT.
        print("Loading optimizer state dictionary...")
        optimizer.load_state_dict(checkpoint["optimizer_state_dict"])

    if args["cosine_annealing"]:
        # LR will be zero as we approach `steps` number of epochs each time.
        # If `steps = 5`, LR will slowly reduce to zero every 5 epochs.
        steps = NUM_EPOCHS + 10
        scheduler = (
            torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(
                optimizer, T_0=steps, T_mult=1, verbose=False
            )
        )
    else:
        scheduler = None

    save_best_model = SaveBestModel()

    for epoch in range(start_epochs, NUM_EPOCHS):
        train_loss_hist.reset()

        (
            _,
            batch_loss_list,
            batch_loss_cls_list,
            batch_loss_box_reg_list,
            batch_loss_objectness_list,
            batch_loss_rpn_list,
        ) = train_one_epoch(
            model,
            optimizer,
            train_loader,
            DEVICE,
            epoch,
            train_loss_hist,
            print_freq=100,
            scheduler=scheduler,
        )
        save_model(
            epoch,
            model,
            optimizer,
            train_loss_list,
            train_loss_list_epoch,
            val_map,
            val_map_05,
            OUT_DIR,
            data_configs,
            args["model"],
        )
        # Save the model dictionary only for the current epoch.
        save_model_state(model, OUT_DIR, data_configs, args["model"])
        # Append the current epoch's batch-wise losses
        # to the `train_loss_list`.
        train_loss_list.extend(batch_loss_list)
        loss_cls_list.append(
            np.mean(
                np.array(
                    batch_loss_cls_list,
                )
            )
        )
        loss_box_reg_list.append(
            np.mean(np.array(batch_loss_box_reg_list))
        )
        loss_objectness_list.append(
            np.mean(np.array(batch_loss_objectness_list))
        )
        loss_rpn_list.append(np.mean(np.array(batch_loss_rpn_list)))

        # Append curent epoch's average loss to `train_loss_list_epoch`.
        train_loss_list_epoch.append(train_loss_hist.value)

        # Save batch-wise train loss plot using TensorBoard.
        tensorboard_loss_log(
            "Train loss",
            np.array(train_loss_list_epoch),
            writer,
            epoch,
        )
        #  if epoch % args['eval_n_epochs'] == 0:
        stats, val_pred_image = evaluate(
            model,
            valid_loader,
            device=DEVICE,
            save_valid_preds=False,
            out_dir=OUT_DIR,
            classes=CLASSES,
            colors=COLORS,
        )
        val_map_05.append(stats[1])
        val_map.append(stats[0])

        if not args["disable_wandb"]:
            wandb_log(
                train_loss_hist.value,
                batch_loss_list,
                loss_cls_list,
                loss_box_reg_list,
                loss_objectness_list,
                loss_rpn_list,
                stats[1],
                stats[0],
                val_pred_image,
                IMAGE_SIZE,
            )

            # Save mAP plot using TensorBoard.
        tensorboard_map_log(
            name="mAP",
            val_map_05=np.array(val_map_05),
            val_map=np.array(val_map),
            writer=writer,
            epoch=epoch,
        )

        # Save best model if the current mAP @0.5:0.95 IoU is
        # greater than the last hightest.
        save_best_model(
            model,
            val_map[-1],
            epoch,
            OUT_DIR,
            data_configs,
            args["model"],
        )
        if not args["disable_wandb"]:
            wandb_save_model(OUT_DIR)


if __name__ == "__main__":
    print("OK")
