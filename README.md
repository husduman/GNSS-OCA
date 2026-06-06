<p align="center">
  <img src="icon/github_banner.png" alt="GNSS-OCA" width="100%">
</p>

# GNSS-OCA: An open-source software for GNSS Orbit and Clock Products analysis 

GNSS-OCA is an open-source software package developed for the analysis, comparison, and quality assessment of GNSS orbit and clock products.

The software provides a graphical user interface (GUI) for downloading, processing, and evaluating SP3 orbit and CLK clock products, antenna calibration files (ATX), and related GNSS datasets.

---

## Features

### Product Download

* Multi-center GNSS product download
* Support for:

  * CODE
  * ESA
  * GFZ
  * CNES
  * JPL
  * MIT
  * IGS
  * WHU
  * WUM
  * HUS
  * and other analysis centers

### Orbit Analysis

* Orbit comparison
* Radial, Along-track, Cross-track (RAC) analysis
* Orbit statistics
* Orbit alignment

### Clock Analysis

* Clock comparison
* Clock frequency analysis
* Clock outlier detection
* Clock statistics

### Additional Tools

* Product availability analysis
* Day-boundary discontinuity analysis
* Hadamard variance analysis
* Satellite metadata utilities
* Sun shadow analysis
* Orbit densification
* Velocity prediction tools

---

## Installation

### 1. Clone repository

```bash
git clone https://github.com/USERNAME/GNSS-OCA.git
cd GNSS-OCA
```

### 2. Create Conda environment

```bash
conda env create -f environment.yml
conda activate gnss-oca
```

### 3. Install package

```bash
pip install -e .
```

### 4. Launch GNSS-OCA

```bash
gnss-oca
```

---

## Requirements

* Python 3.12+
* NumPy
* Pandas
* SciPy
* Requests
* Tkinter
* tkcalendar

---

## Authors

* Hüseyin DUMAN
* Salih Sermet Öğütçü
* Salih Alçay

---

## Citation

If you use GNSS-OCA in scientific research, please cite the software using the information provided in the CITATION.cff file.

---

## License

This project is distributed under the MIT License.

---

## Acknowledgements

The development of GNSS-OCA has benefited from research activities in GNSS orbit and clock analysis, precise positioning, geodesy, and Earth observation studies.
