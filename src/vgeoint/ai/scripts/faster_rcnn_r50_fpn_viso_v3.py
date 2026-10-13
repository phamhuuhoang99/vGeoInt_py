# Faster R-CNN R-50-FPN — VISO v3 (class-balanced + anti-overfitting)
# ====================================================================
# Changes vs v2:
#   1. ClassBalancedDataset — oversample plane/ship/train (car=99.5% → balanced)
#   2. 12-epoch schedule — best mAP was at epoch 2 in v2, overfitting after
#   3. EarlyStoppingHook — stop if no improvement for 4 val rounds
#   4. Save best checkpoint by mAP
#   5. val_interval=1 — validate every epoch to catch peak
#   6. Lower LR (0.001) + step schedule at [8,11]
#   7. Stronger weight decay (0.0005) to reduce overfitting
#   8. Freeze backbone stages 0-1 — reduce overfitting on small dataset
#
# Root cause addressed: v2 overfits to car class (525K anns) and forgets
# plane (1.3K), ship (1K), train (198). ClassBalancedDataset with
# oversample_thr=0.5 will upsample images containing rare classes.

default_scope = "mmdet"

default_hooks = dict(
    timer=dict(type="IterTimerHook"),
    logger=dict(type="LoggerHook", interval=50),
    param_scheduler=dict(type="ParamSchedulerHook"),
    checkpoint=dict(
        type="CheckpointHook",
        interval=1,
        max_keep_ckpts=5,
        save_best="coco/bbox_mAP",  # keep best checkpoint by mAP
        rule="greater",
    ),
    sampler_seed=dict(type="DistSamplerSeedHook"),
    visualization=dict(type="DetVisualizationHook"),
)

custom_hooks = [
    dict(
        type="EarlyStoppingHook",
        monitor="coco/bbox_mAP",
        patience=5,            # stop if no improvement for 5 consecutive evals
        min_delta=0.001,
        rule="greater",
    ),
]

env_cfg = dict(
    cudnn_benchmark=False,
    mp_cfg=dict(mp_start_method="fork", opencv_num_threads=0),
    dist_cfg=dict(backend="nccl"),
)

vis_backends = [dict(type="LocalVisBackend")]
visualizer = dict(
    type="DetLocalVisualizer",
    vis_backends=vis_backends,
    name="visualizer",
)

log_processor = dict(type="LogProcessor", window_size=50, by_epoch=True)
log_level = "INFO"
load_from = None
resume = False

# ------------------------------------------------------------------ #
# Schedule — 12 epochs, MultiStep LR (more stable than cosine for small data)
# ------------------------------------------------------------------ #
max_epochs = 12

train_cfg = dict(type="EpochBasedTrainLoop", max_epochs=max_epochs, val_interval=1)
val_cfg   = dict(type="ValLoop")
test_cfg  = dict(type="TestLoop")

param_scheduler = [
    dict(
        type="LinearLR",
        start_factor=0.001,
        by_epoch=False,
        begin=0,
        end=500,
    ),
    dict(
        type="MultiStepLR",
        begin=0,
        end=max_epochs,
        by_epoch=True,
        milestones=[8, 11],
        gamma=0.1,
    ),
]

optim_wrapper = dict(
    type="OptimWrapper",
    optimizer=dict(type="SGD", lr=0.001, momentum=0.9, weight_decay=0.0005),
    clip_grad=dict(max_norm=35, norm_type=2),
)

auto_scale_lr = dict(enable=True, base_batch_size=16)

# ------------------------------------------------------------------ #
# Model — same architecture as v2 (small-object anchors)
# ------------------------------------------------------------------ #
num_classes = 4

model = dict(
    type="FasterRCNN",
    data_preprocessor=dict(
        type="DetDataPreprocessor",
        mean=[123.675, 116.28, 103.53],
        std=[58.395, 57.12, 57.375],
        bgr_to_rgb=True,
        pad_size_divisor=32,
    ),
    backbone=dict(
        type="ResNet",
        depth=50,
        num_stages=4,
        out_indices=(0, 1, 2, 3),
        frozen_stages=1,        # freeze stage 0-1 to reduce overfitting (v2 was -1)
        norm_cfg=dict(type="BN", requires_grad=True),
        norm_eval=True,         # freeze BN stats (v2 was False → BN drift caused overfitting)
        style="pytorch",
        init_cfg=dict(type="Pretrained", checkpoint="torchvision://resnet50"),
    ),
    neck=dict(
        type="FPN",
        in_channels=[256, 512, 1024, 2048],
        out_channels=256,
        num_outs=5,
    ),
    rpn_head=dict(
        type="RPNHead",
        in_channels=256,
        feat_channels=256,
        anchor_generator=dict(
            type="AnchorGenerator",
            # Same small-object anchors as v2 — this was the key v1→v2 fix
            # P2: 4,8,16px | P3: 8,16,32px | covers 5-8px cars
            scales=[1, 2, 4],
            ratios=[0.5, 1.0, 2.0],
            strides=[4, 8, 16, 32, 64],
        ),
        bbox_coder=dict(
            type="DeltaXYWHBBoxCoder",
            target_means=[0.0, 0.0, 0.0, 0.0],
            target_stds=[1.0, 1.0, 1.0, 1.0],
        ),
        loss_cls=dict(type="CrossEntropyLoss", use_sigmoid=True, loss_weight=1.0),
        loss_bbox=dict(type="SmoothL1Loss", beta=1.0 / 9.0, loss_weight=1.0),
    ),
    roi_head=dict(
        type="StandardRoIHead",
        bbox_roi_extractor=dict(
            type="SingleRoIExtractor",
            roi_layer=dict(type="RoIAlign", output_size=7, sampling_ratio=2),
            out_channels=256,
            featmap_strides=[4, 8, 16, 32],
        ),
        bbox_head=dict(
            type="Shared2FCBBoxHead",
            in_channels=256,
            fc_out_channels=1024,
            roi_feat_size=7,
            num_classes=num_classes,
            bbox_coder=dict(
                type="DeltaXYWHBBoxCoder",
                target_means=[0.0, 0.0, 0.0, 0.0],
                target_stds=[0.1, 0.1, 0.2, 0.2],
            ),
            reg_class_agnostic=False,
            loss_cls=dict(type="CrossEntropyLoss", use_sigmoid=False, loss_weight=1.0),
            loss_bbox=dict(type="SmoothL1Loss", beta=1.0, loss_weight=1.0),
        ),
    ),
    # Same lowered IoU thresholds as v2 (critical for tiny objects)
    train_cfg=dict(
        rpn=dict(
            assigner=dict(
                type="MaxIoUAssigner",
                pos_iou_thr=0.5,
                neg_iou_thr=0.15,
                min_pos_iou=0.2,
                match_low_quality=True,
                ignore_iof_thr=-1,
            ),
            sampler=dict(
                type="RandomSampler",
                num=256,
                pos_fraction=0.5,
                neg_pos_ub=-1,
                add_gt_as_proposals=False,
            ),
            allowed_border=-1,
            pos_weight=-1,
            debug=False,
        ),
        rpn_proposal=dict(
            nms_pre=4000,
            max_per_img=2000,
            nms=dict(type="nms", iou_threshold=0.7),
            min_bbox_size=0,
        ),
        rcnn=dict(
            assigner=dict(
                type="MaxIoUAssigner",
                pos_iou_thr=0.4,
                neg_iou_thr=0.4,
                min_pos_iou=0.3,
                match_low_quality=False,
                ignore_iof_thr=-1,
            ),
            sampler=dict(
                type="RandomSampler",
                num=512,
                pos_fraction=0.25,
                neg_pos_ub=-1,
                add_gt_as_proposals=True,
            ),
            pos_weight=-1,
            debug=False,
        ),
    ),
    test_cfg=dict(
        rpn=dict(
            nms_pre=2000,
            max_per_img=2000,
            nms=dict(type="nms", iou_threshold=0.7),
            min_bbox_size=0,
        ),
        rcnn=dict(
            score_thr=0.05,
            nms=dict(type="nms", iou_threshold=0.5),
            max_per_img=1000,
        ),
    ),
)

# ------------------------------------------------------------------ #
# Dataset — with ClassBalancedDataset wrapper
# ------------------------------------------------------------------ #
DATA_ROOT   = r"d:/Code Train/VISODATA_test/data-train/coco"
ANN_ROOT    = r"d:/Code Train/VISODATA_test/data/merged_coco/annotations"

dataset_type = "CocoDataset"
metainfo = dict(classes=("car", "plane", "ship", "train"))

train_pipeline = [
    dict(type="LoadImageFromFile"),
    dict(type="LoadAnnotations", with_bbox=True),
    dict(
        type="RandomResize",
        scale=[(800, 800), (1024, 1024)],
        keep_ratio=True,
    ),
    dict(type="RandomFlip", prob=0.5, direction="horizontal"),
    dict(type="RandomFlip", prob=0.5, direction="vertical"),
    dict(
        type="PhotoMetricDistortion",
        brightness_delta=32,
        contrast_range=(0.5, 1.5),
        saturation_range=(0.5, 1.5),
        hue_delta=18,
    ),
    dict(type="PackDetInputs"),
]

val_pipeline = [
    dict(type="LoadImageFromFile"),
    dict(type="Resize", scale=(1024, 1024), keep_ratio=True),
    dict(type="LoadAnnotations", with_bbox=True),
    dict(
        type="PackDetInputs",
        meta_keys=("img_id", "img_path", "ori_shape", "img_shape", "scale_factor"),
    ),
]
test_pipeline = val_pipeline

# Inner dataset (raw COCO)
_train_dataset = dict(
    type=dataset_type,
    metainfo=metainfo,
    data_root=DATA_ROOT,
    ann_file=ANN_ROOT + "/instances_train2017.json",
    data_prefix=dict(img=""),
    filter_cfg=dict(filter_empty_gt=True, min_size=1),
    pipeline=train_pipeline,
)

train_dataloader = dict(
    batch_size=2,
    num_workers=2,
    persistent_workers=True,
    sampler=dict(type="DefaultSampler", shuffle=True),
    batch_sampler=dict(type="AspectRatioBatchSampler"),
    dataset=dict(
        # ClassBalancedDataset oversamples images containing rare categories
        # oversample_thr=0.5: categories appearing in <50% of images get oversampled
        # car appears in most images → not oversampled
        # plane (1.3K/11K imgs), ship (1K), train (198) → heavily oversampled
        type="ClassBalancedDataset",
        oversample_thr=0.5,
        dataset=_train_dataset,
    ),
)

val_dataloader = dict(
    batch_size=1,
    num_workers=2,
    persistent_workers=True,
    drop_last=False,
    sampler=dict(type="DefaultSampler", shuffle=False),
    dataset=dict(
        type=dataset_type,
        metainfo=metainfo,
        data_root=DATA_ROOT,
        ann_file=ANN_ROOT + "/instances_val2017.json",
        data_prefix=dict(img=""),
        test_mode=True,
        pipeline=val_pipeline,
    ),
)

test_dataloader = val_dataloader

val_evaluator = dict(
    type="CocoMetric",
    ann_file=ANN_ROOT + "/instances_val2017.json",
    metric="bbox",
    classwise=True,
    format_only=False,
)

test_evaluator = dict(
    type="CocoMetric",
    ann_file=ANN_ROOT + "/instances_test2017.json",
    metric="bbox",
    classwise=True,
    format_only=False,
)

# ------------------------------------------------------------------ #
# Work dir
# ------------------------------------------------------------------ #
work_dir = r"d:/Code Train/VISODATA_test/work_dirs/faster_rcnn_r50_fpn_viso_v3"
