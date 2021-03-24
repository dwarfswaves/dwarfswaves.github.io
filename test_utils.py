import unittest
import utils 
import pandas as pd 
import numpy as np
import torch

test_data = pd.read_csv('gaia_example_data.csv')
device = 'cuda' if torch.cuda.is_available() else 'cpu'

median_ra = 2.5
median_dec = 0
gnomonic_width = 0.0175
pmfield_size = 5.0 
grid_size = 96 
data, x, y = utils.mask_data(test_data, median_ra, median_dec, gnomonic_width, pmfield_size)

class TestStringMethods(unittest.TestCase):
	def test_gnominic(self):
		x, y = utils.to_gnomonic(test_data['ra'],test_data['dec'],median_ra, median_dec)
		ra, dec = utils.from_gnomonic(x, y, median_ra, median_dec)
		self.assertEqual(np.round(np.sum(ra-test_data['ra']), 10), 0)
		self.assertEqual(np.round(np.sum(dec-test_data['dec']), 10), 0)

	def test_masking(self):
		data, x, y = utils.mask_data(test_data, median_ra, median_dec, gnomonic_width, pmfield_size)
		self.assertTrue(np.max(x) < gnomonic_width)
		self.assertTrue(np.min(x) > -gnomonic_width)
		self.assertTrue(np.max(y) < gnomonic_width)
		self.assertTrue(np.min(y) > -gnomonic_width)
		self.assertTrue(np.max(data['pmra']) < pmfield_size)
		self.assertTrue(np.min(data['pmra']) > -pmfield_size)
		self.assertTrue(np.max(data['pmdec']) < pmfield_size)
		self.assertTrue(np.min(data['pmdec']) > -pmfield_size)

	def test_make_random(self):
		randx, randy, rand_pmra, rand_pmdec = utils.make_random_image(data, x, y, gnomonic_width, pmfield_size)
		self.assertEqual(len(randx), len(randy))
		self.assertEqual(len(randx), len(rand_pmra))
		self.assertTrue(np.max(randx) < gnomonic_width)
		self.assertTrue(np.max(randy) < gnomonic_width)
		self.assertTrue(len(randx) > 100) 

	def test_make_field(self):
		full_field = np.c_[test_data['ra'], test_data['dec'], test_data['pmra'], test_data['pmdec']]
		field_image, edges = utils.make_field_image(full_field, gnomonic_width, pmfield_size, grid_size)
		self.assertEqual(field_image.shape, (96, 96, 96, 96)) 

	def test_find_blobs(self):
		edge_size = 24
		front = int(edge_size)
		back = int(grid_size-edge_size)
		out1 = np.zeros((grid_size, grid_size, grid_size, grid_size))
		out1[front:back,front:back,front:back,front:back] = 25
		blobs, significance = utils.find_blobs(out1, threshold=20)
		self.assertEqual(significance[0], 25.)
		self.assertEqual(blobs[0][0], 47.5)
		self.assertEqual(blobs[0][5], 55.413596550545826) 

	def test_find_clusters(self):
		blobs = [[50., 50.,  20., 20., 20., 20., 15., 15.]]
		stars = utils.find_clusters(data, x, y, gnomonic_width, pmfield_size, grid_size, blobs)
		self.assertEqual(len(stars[0]), 18)

	def test_wavelet_transform(self):
		edge_size = 24
		front = int(edge_size)
		back = int(grid_size-edge_size)
		out1 = np.zeros((grid_size, grid_size, grid_size, grid_size))
		out1[front:back,front:back,front:back,front:back] = 25
		wv = utils.WaveNet(grid_size, grid_size, J=4, wavelets = ['bior5.5'])
		out = wv(torch.Tensor(out1).to(device)).to('cpu').numpy()
		self.assertEqual(out.shape, (96, 96, 96, 96))

if __name__ == '__main__':
    unittest.main()
