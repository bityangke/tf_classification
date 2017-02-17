from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import argparse
import logging
import numpy as np
import tensorflow as tf
import tensorflow.contrib.slim as slim

from config.parse_config import parse_config_file
from nets import nets_factory
from preprocessing import inputs

def test(tfrecords, checkpoint_path, savedir, max_iterations, eval_interval_secs, cfg):
    """
    Args:
        tfrecords (list)
        checkpoint_path (str)
        savedir (str)
        max_iterations (int)
        cfg (EasyDict)
    """
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    tf.logging.set_verbosity(tf.logging.DEBUG)

    graph = tf.Graph()

    with graph.as_default():

        global_step = slim.get_or_create_global_step()

        batch_dict = inputs.input_nodes(
            tfrecords=tfrecords,
            cfg=cfg.IMAGE_PROCESSING,
            num_epochs=1,
            batch_size=cfg.BATCH_SIZE,
            num_threads=cfg.NUM_INPUT_THREADS,
            shuffle_batch =cfg.SHUFFLE_QUEUE,
            random_seed=cfg.RANDOM_SEED,
            capacity=cfg.QUEUE_CAPACITY,
            min_after_dequeue=cfg.QUEUE_MIN,
            add_summaries=False,
            visualize=False
        )

        arg_scope = nets_factory.arg_scopes_map[cfg.MODEL_NAME](
            weight_decay=cfg.WEIGHT_DECAY,
            batch_norm_decay=cfg.BATCHNORM_MOVING_AVERAGE_DECAY,
            batch_norm_epsilon=cfg.BATCHNORM_EPSILON
        )

        with slim.arg_scope(arg_scope):
            logits, end_points = nets_factory.networks_map[cfg.MODEL_NAME](
                inputs=batch_dict['inputs'],
                num_classes=cfg.NUM_CLASSES,
                dropout_keep_prob=cfg.DROPOUT_KEEP_PROB,
                is_training=False
            )


        variable_averages = tf.train.ExponentialMovingAverage(
            cfg.MOVING_AVERAGE_DECAY, global_step)
        variables_to_restore = variable_averages.variables_to_restore(
            slim.get_model_variables())
        variables_to_restore[global_step.op.name] = global_step

        predictions = end_points['Predictions']
        labels = tf.squeeze(batch_dict['labels'])

        # Define the metrics:
        metric_map = {
            'Accuracy': tf.metrics.accuracy(labels=labels, predictions=tf.argmax(predictions, 1))
        }
        if len(cfg.PRECISION_AT_K_METRIC) > 0:
            for k in cfg.PRECISION_AT_K_METRIC:
                metric_map['Precision@%s' % k] = tf.metrics.sparse_average_precision_at_k(labels=labels, predictions=predictions, k=k)

        names_to_values, names_to_updates = slim.metrics.aggregate_metric_map(metric_map)

        # Print the summaries to screen.
        for name, value in names_to_values.iteritems():
            summary_name = 'eval/%s' % name
            op = tf.summary.scalar(summary_name, value, collections=[])
            op = tf.Print(op, [value], summary_name)
            tf.add_to_collection(tf.GraphKeys.SUMMARIES, op)


        if max_iterations > 0:
            num_batches = max_iterations
        else:
            # This ensures that we make a single pass over all of the data.
            # We could use ceil if the batch queue is allowed to pad the last batch
            num_batches = np.floor(cfg.NUM_TEST_EXAMPLES / float(cfg.BATCH_SIZE))


        sess_config = tf.ConfigProto(
            log_device_placement=cfg.SESSION_CONFIG.LOG_DEVICE_PLACEMENT,
            allow_soft_placement = True,
            gpu_options = tf.GPUOptions(
                per_process_gpu_memory_fraction=cfg.SESSION_CONFIG.PER_PROCESS_GPU_MEMORY_FRACTION
            )
        )

        if eval_interval_secs > 0:

            slim.evaluation.evaluation_loop(
                master='',
                checkpoint_dir=checkpoint_path,
                logdir=savedir,
                num_evals=num_batches,
                initial_op=None,
                initial_op_feed_dict=None,
                eval_op=names_to_updates.values(),
                eval_op_feed_dict=None,
                final_op=None,
                final_op_feed_dict=None,
                summary_op=tf.summary.merge_all(),
                summary_op_feed_dict=None,
                variables_to_restore=variables_to_restore,
                eval_interval_secs=eval_interval_secs,
                max_number_of_evaluations=None,
                session_config=sess_config,
                timeout=None
            )

        else:
            if tf.gfile.IsDirectory(checkpoint_path):
                checkpoint_path = tf.train.latest_checkpoint(checkpoint_path)
            tf.logging.info('Evaluating %s' % checkpoint_path)

            slim.evaluation.evaluate_once(
                master='',
                checkpoint_path=checkpoint_path,
                logdir=savedir,
                num_evals=num_batches,
                eval_op=names_to_updates.values(),
                variables_to_restore=variables_to_restore,
                session_config=sess_config
            )

def parse_args():

    parser = argparse.ArgumentParser(description='Test the person classifier')

    parser.add_argument('--tfrecords', dest='tfrecords',
                        help='Paths to tfrecords.', type=str,
                        nargs='+', required=True)

    parser.add_argument('--savedir', dest='savedir',
                          help='Path to directory to store summary files.', type=str,
                          required=True)

    parser.add_argument('--checkpoint_path', dest='checkpoint_path',
                          help='Path to a specific model to test against. If a directory, then the newest checkpoint file will be used.', type=str,
                          required=True, default=None)

    parser.add_argument('--config', dest='config_file',
                        help='Path to the configuration file.',
                        required=True, type=str)

    parser.add_argument('--eval_interval_secs', dest='eval_interval_secs',
                        help='Go into an evaluation loop, waiting this many seconds between evaluations. Default is to evaluate once.',
                        required=False, type=int, default=0)

    parser.add_argument('--batch_size', dest='batch_size',
                        help='The number of images in a batch.',
                        required=False, type=int, default=None)

    parser.add_argument('--batches', dest='batches',
                        help='Maximum number of iterations to run. Default is all records (modulo the batch size).',
                        required=False, type=int, default=0)

    parser.add_argument('--model_name', dest='model_name',
                        help='The name of the architecture to use.',
                        required=False, type=str, default=None)

    args = parser.parse_args()
    return args

def main():

    args = parse_args()

    cfg = parse_config_file(args.config_file)

    if args.batch_size != None:
        cfg.BATCH_SIZE = args.batch_size

    if args.model_name != None:
        cfg.MODEL_NAME = args.model_name

    test(
        tfrecords=args.tfrecords,
        checkpoint_path=args.checkpoint_path,
        savedir=args.savedir,
        max_iterations=args.batches,
        eval_interval_secs=args.eval_interval_secs,
        cfg=cfg
    )

if __name__ == '__main__':
    main()