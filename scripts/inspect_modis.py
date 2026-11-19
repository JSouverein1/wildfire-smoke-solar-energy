"""Inspect a raw NASA MCD06COSP .nc file, showing variables without loading arrays."""
import argparse
import h5py

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file',help='Path to MCD06COSP_D3_MODIS .nc file')
    args=parser.parse_args()
    with h5py.File(args.file) as nc:
        for name in ('latitude','longitude','Cloud_Mask_Fraction/Mean',
                     'Cloud_Mask_Fraction/Pixel_Counts'):
            item=nc[name]
            print(f'{name}: shape={item.shape} dtype={item.dtype}')

if __name__=='__main__':main()
