#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OTB Image Blending/Pansharpening Tool
====================================

This script provides image blending functionality using Orfeo ToolBox (OTB)
pansharpening algorithms. It supports multiple methods including RCS, LMVM,
and Bayesian fusion techniques.

Author: vGeoInt_v2 Development Team
Date: 2025
Version: 1.0

Requirements:
- OTB 9.1.0 or higher
- Python 3.7+
- Access to OTB command line tools

Usage:
    python otb_image_blending.py <pan_image> <ms_image> <output> <method> [params...]

Supported Methods:
    - RCS: Resolution-Preserving Color-Sharpening
    - LMVM: Local Mean and Variance Matching
    - Bayesian: Bayesian Data Fusion
"""

import subprocess
import os
import sys
import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, Any
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('otb_blending.log', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

class OTBImageBlender:
    """
    OTB Image Blending/Pansharpening processor using command line interface.

    This class provides a modern C++20-style interface for OTB pansharpening
    operations with robust error handling and progress reporting.
    """

    # Class constants (C++20 constexpr style)
    DEFAULT_OTB_PATH = r"C:\OTB-9.1.0-Win64\bin\otbcli_Pansharpening.bat"
    SUPPORTED_FORMATS = ['.tif', '.tiff', '.jp2', '.jpg', '.png', '.img', '.hdr']

    # Default parameters for each method
    DEFAULT_PARAMS = {
        'rcs': {'radiusx': 9, 'radiusy': 9},
        'lmvm': {'radiusx': 3, 'radiusy': 3},
        'bayes': {'lambda_weight': 0.9999, 's': 1.0}
    }

    def __init__(self, otb_path: Optional[str] = None):
        """
        Initialize the OTB Image Blender.

        Args:
            otb_path: Path to OTB pansharpening executable
        """
        self.otb_path = otb_path or self.DEFAULT_OTB_PATH
        self.validate_otb_installation()

    def validate_otb_installation(self) -> bool:
        """
        Validate OTB installation and accessibility.

        Returns:
            bool: True if OTB is accessible, False otherwise

        Raises:
            FileNotFoundError: If OTB executable is not found
        """
        if not os.path.exists(self.otb_path):
            error_msg = f"OTB executable not found at: {self.otb_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        logger.info(f"✓ OTB installation found: {self.otb_path}")
        return True

    def validate_inputs(self, pan_path: str, ms_path: str, output_path: str) -> bool:
        """
        Validate input files and output path.

        Args:
            pan_path: Path to panchromatic image
            ms_path: Path to multispectral image
            output_path: Path for output file

        Returns:
            bool: True if validation passes

        Raises:
            FileNotFoundError: If input files don't exist
            ValueError: If file formats are not supported
        """
        # Check input files exist
        if not os.path.exists(pan_path):
            raise FileNotFoundError(f"Panchromatic image not found: {pan_path}")

        if not os.path.exists(ms_path):
            raise FileNotFoundError(f"Multispectral image not found: {ms_path}")

        # Check file formats
        pan_ext = Path(pan_path).suffix.lower()
        ms_ext = Path(ms_path).suffix.lower()

        if pan_ext not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported panchromatic format: {pan_ext}")

        if ms_ext not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported multispectral format: {ms_ext}")

        # Check output directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            logger.info(f"Created output directory: {output_dir}")

        logger.info("✓ Input validation passed")
        return True

    def build_command(self, pan_path: str, ms_path: str, output_path: str,
                     method: str, **method_params) -> list[str]:
        """
        Build OTB command with modern C++20-style parameter handling.

        Args:
            pan_path: Path to panchromatic image
            ms_path: Path to multispectral image
            output_path: Path for output file
            method: Pansharpening method ('rcs', 'lmvm', 'bayes')
            **method_params: Method-specific parameters

        Returns:
            list[str]: Command arguments

        Raises:
            ValueError: If method is not supported
        """
        if method not in self.DEFAULT_PARAMS:
            raise ValueError(f"Unsupported method: {method}")

        # Base command
        cmd = [
            self.otb_path,
            "-inp", os.path.abspath(pan_path),
            "-inxs", os.path.abspath(ms_path)
        ]

        # Add method-specific parameters
        if method == "rcs":
            radiusx = method_params.get("radiusx", self.DEFAULT_PARAMS['rcs']['radiusx'])
            radiusy = method_params.get("radiusy", self.DEFAULT_PARAMS['rcs']['radiusy'])
            cmd.extend([
                "-method", "rcs",
                "-method.rcs.radiusx", str(radiusx),
                "-method.rcs.radiusy", str(radiusy)
            ])
            logger.info(f"✓ RCS parameters: radiusx={radiusx}, radiusy={radiusy}")

        elif method == "lmvm":
            radiusx = method_params.get("radiusx", self.DEFAULT_PARAMS['lmvm']['radiusx'])
            radiusy = method_params.get("radiusy", self.DEFAULT_PARAMS['lmvm']['radiusy'])
            cmd.extend([
                "-method", "lmvm",
                "-method.lmvm.radiusx", str(radiusx),
                "-method.lmvm.radiusy", str(radiusy)
            ])
            logger.info(f"✓ LMVM parameters: radiusx={radiusx}, radiusy={radiusy}")

        elif method == "bayes":
            lambda_weight = method_params.get("lambda_weight", self.DEFAULT_PARAMS['bayes']['lambda_weight'])
            s_coeff = method_params.get("s", self.DEFAULT_PARAMS['bayes']['s'])
            cmd.extend([
                "-method", "bayes",
                "-method.bayes.lambda", str(lambda_weight),
                "-method.bayes.s", str(s_coeff)
            ])
            logger.info(f"✓ Bayesian parameters: lambda={lambda_weight}, s={s_coeff}")

        # Add output
        cmd.extend(["-out", os.path.abspath(output_path)])

        return cmd

    def execute_blending(self, pan_path: str, ms_path: str, output_path: str,
                        method: str = "rcs", timeout: int = 300,
                        **method_params) -> Tuple[bool, str]:
        """
        Execute image blending with comprehensive error handling.

        Args:
            pan_path: Path to panchromatic image
            ms_path: Path to multispectral image
            output_path: Path for output file
            method: Pansharpening method
            timeout: Process timeout in seconds
            **method_params: Method-specific parameters

        Returns:
            Tuple[bool, str]: (success, message)
        """
        try:
            # Validate inputs
            self.validate_inputs(pan_path, ms_path, output_path)

            # Build command
            cmd = self.build_command(pan_path, ms_path, output_path, method, **method_params)

            logger.info(f"Executing command: {' '.join(cmd)}")
            logger.info(f"Using method: {method.upper()}")

            # Record start time
            start_time = time.time()

            # Execute command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8',
                errors='replace'
            )

            # Record end time
            end_time = time.time()
            processing_time = end_time - start_time

            if result.returncode == 0:
                success_msg = f"✓ Pansharpening completed successfully in {processing_time:.2f} seconds!"
                logger.info(success_msg)

                # Log output file info
                if os.path.exists(output_path):
                    file_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
                    logger.info(f"✓ Output file created: {output_path} ({file_size:.2f} MB)")

                if result.stdout:
                    logger.debug(f"OTB Output: {result.stdout}")

                return True, success_msg
            else:
                error_msg = f"✗ Command failed with return code: {result.returncode}"
                logger.error(error_msg)

                if result.stderr:
                    logger.error(f"Error details: {result.stderr}")
                    error_msg += f"\nError: {result.stderr}"

                if result.stdout:
                    logger.info(f"Output: {result.stdout}")

                return False, error_msg

        except subprocess.TimeoutExpired:
            error_msg = f"✗ Process timed out after {timeout} seconds"
            logger.error(error_msg)
            return False, error_msg

        except Exception as e:
            error_msg = f"✗ Unexpected error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def get_method_info(self) -> Dict[str, Any]:
        """
        Get information about available methods and their parameters.

        Returns:
            Dict[str, Any]: Method information
        """
        return {
            "methods": {
                "rcs": {
                    "name": "Resolution-Preserving Color-Sharpening",
                    "description": "Fast and efficient pansharpening method",
                    "parameters": {
                        "radiusx": {"type": "int", "range": [1, 50], "default": 9},
                        "radiusy": {"type": "int", "range": [1, 50], "default": 9}
                    }
                },
                "lmvm": {
                    "name": "Local Mean and Variance Matching",
                    "description": "High-quality pansharpening with local statistics",
                    "parameters": {
                        "radiusx": {"type": "int", "range": [1, 50], "default": 3},
                        "radiusy": {"type": "int", "range": [1, 50], "default": 3}
                    }
                },
                "bayes": {
                    "name": "Bayesian Data Fusion",
                    "description": "Advanced statistical fusion method",
                    "parameters": {
                        "lambda_weight": {"type": "float", "range": [0.0001, 0.9999], "default": 0.9999},
                        "s": {"type": "float", "range": [0.1, 10.0], "default": 1.0}
                    }
                }
            },
            "supported_formats": self.SUPPORTED_FORMATS
        }

def create_config_file(output_path: str = "blending_config.json") -> None:
    """Create a configuration file with default settings."""
    blender = OTBImageBlender()
    config = {
        "otb_path": blender.otb_path,
        "default_method": "rcs",
        "default_timeout": 300,
        "methods": blender.get_method_info()["methods"]
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logger.info(f"Configuration file created: {output_path}")

def main():
    """Main function with comprehensive CLI interface."""
    parser = argparse.ArgumentParser(
        description="OTB Image Blending/Pansharpening Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # RCS method with default parameters
  python otb_image_blending.py pan.tif ms.tif output.tif rcs

  # LMVM method with custom radius
  python otb_image_blending.py pan.tif ms.tif output.tif lmvm --radiusx 5 --radiusy 5

  # Bayesian method with custom parameters
  python otb_image_blending.py pan.tif ms.tif output.tif bayes --lambda_weight 0.95 --s 1.2

  # Generate configuration file
  python otb_image_blending.py --create-config
        """
    )

    parser.add_argument("pan_image", nargs='?', help="Panchromatic image path")
    parser.add_argument("ms_image", nargs='?', help="Multispectral image path")
    parser.add_argument("output", nargs='?', help="Output image path")
    parser.add_argument("method", nargs='?', choices=['rcs', 'lmvm', 'bayes'],
                       default='rcs', help="Pansharpening method")

    # Method-specific parameters
    parser.add_argument("--radiusx", type=int, help="Radius X for RCS/LMVM methods")
    parser.add_argument("--radiusy", type=int, help="Radius Y for RCS/LMVM methods")
    parser.add_argument("--lambda_weight", type=float, help="Lambda weight for Bayesian method")
    parser.add_argument("--s", type=float, help="S coefficient for Bayesian method")

    # General options
    parser.add_argument("--otb-path", help="Path to OTB executable")
    parser.add_argument("--timeout", type=int, default=300, help="Process timeout in seconds")
    parser.add_argument("--create-config", action="store_true", help="Create configuration file")
    parser.add_argument("--info", action="store_true", help="Show method information")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Handle special commands
    if args.create_config:
        create_config_file()
        return 0

    if args.info:
        blender = OTBImageBlender(args.otb_path)
        info = blender.get_method_info()
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0

    # Validate required arguments
    if not all([args.pan_image, args.ms_image, args.output]):
        parser.error("pan_image, ms_image, and output are required")

    try:
        # Initialize blender
        blender = OTBImageBlender(args.otb_path)

        # Prepare method parameters
        method_params = {}
        if args.method in ['rcs', 'lmvm']:
            if args.radiusx is not None:
                method_params['radiusx'] = args.radiusx
            if args.radiusy is not None:
                method_params['radiusy'] = args.radiusy
        elif args.method == 'bayes':
            if args.lambda_weight is not None:
                method_params['lambda_weight'] = args.lambda_weight
            if args.s is not None:
                method_params['s'] = args.s

        # Execute blending
        logger.info("="*50)
        logger.info("OTB Image Blending/Pansharpening")
        logger.info("="*50)

        success, message = blender.execute_blending(
            args.pan_image,
            args.ms_image,
            args.output,
            args.method,
            args.timeout,
            **method_params
        )

        if success:
            logger.info("Process completed successfully!")
            return 0
        else:
            logger.error("Process failed!")
            logger.error(message)
            return 1

    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
