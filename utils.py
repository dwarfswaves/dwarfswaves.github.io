import numpy as np 
import pandas as pd 
import scipy.stats
from scipy import ndimage
from sklearn.mixture import GaussianMixture as GMM
import torch
import torch.nn as nn
import torch.nn.functional as F
from pytorch_wavelets import DWTForward, DWTInverse

device = 'cuda' if torch.cuda.is_available() else 'cpu'


#https://mathworld.wolfram.com/GnomonicProjection.html

def to_gnomonic(ra,dec,median_ra, median_dec):
    '''Transforms RA and DEC to gnomonic projection 

    Args:
        ra, dec (float or 1D array): list of ra and dec values 
        median_ra, median_dec (float): coordinates of projection center

    Returns:
        x, y (float or 1D array): gnomonic coordinates 
    '''

    ra = ra/360.*2*np.pi
    median_ra = median_ra/360.*2*np.pi
    dec = dec/180.*np.pi
    median_dec = median_dec/180.*np.pi
    cosc = np.sin(median_dec)*np.sin(dec) + np.cos(median_dec)*np.cos(dec)*np.cos(ra-median_ra)
    x = (np.cos(dec)*np.sin(ra-median_ra))/cosc
    y = (np.cos(median_dec)*np.sin(dec)-np.sin(median_dec)*np.cos(dec)*np.cos(ra-median_ra))/cosc
    return x, y

def from_gnomonic(x, y, median_ra, median_dec):
    '''Transforms gnomonic projection from RA and DEC 

    Args:
        x, y (float or 1D array): list gnomonic coordinate values 
        median_ra, median_dec (float): coordinates of projection center

    Returns:
        ra, dec (float or 1D array): ra and dec coordinates 
    '''

    median_ra = median_ra/360.*2*np.pi
    median_dec = median_dec/180.*np.pi
    ro = np.sqrt(x**2+y**2)
    c = np.arctan(ro)
    dec = np.arcsin(np.cos(c)*np.sin(median_dec) + (y*np.sin(c)*np.cos(median_dec))/ro)
    ra  = median_ra + np.arctan((x*np.sin(c))/(ro*np.cos(median_dec)*np.cos(c)-y*np.sin(median_dec)*np.sin(c)))
    dec = dec*180./np.pi
    ra = ra*360./(2*np.pi)
    return ra, dec

#mask data (mainly pmra and parallax)
def mask_data(data, median_ra, median_dec, gnomonic_width, pmfield_size):
    '''Applies masking to Gaia data (Darragh-Ford et. al., 2021) and gnomonic projection  

    Args:
        data (pandas DataFrame): Dataframe containing Gaia data (minimum columns ['ra', 'dec', 'pmra', 'pmdec', 
                                 'parallax','parallax_error'])
        median_ra, median_dec (float): coordinates of gnomonic projection center
        gnomonic_width (float): width of gnomonic field 
        pmfield_size (float): width of proper motion field (assumed to be centered at (0,0))

    Returns:
        data (pandas DataFrame): Gaia data with masking applied 
        x, y (1D float array): gnomonic projections of ra and dec 
 
    '''
    x,y = to_gnomonic(data['ra'], data['dec'],median_ra,median_dec)
    mask = x > -gnomonic_width
    mask1 = x < gnomonic_width
    mask2 = y > -gnomonic_width
    mask3 = y < gnomonic_width
    mask4 = data['parallax'] - 3*data['parallax_error'] <  0 #variables['max_parallax']
    mask5 = (np.invert(np.isnan(data['parallax'])))
    mask6 = (np.invert(np.isnan(data['ra'])))
    mask7 = (np.invert(np.isnan(data['dec'])))
    mask8 = (np.invert(np.isnan(data['pmra'])))
    mask9 = (np.invert(np.isnan(data['pmdec'])))
    mask10 = data['pmra'] > -pmfield_size
    mask11 = data['pmra'] < pmfield_size
    mask12 = data['pmdec'] > -pmfield_size
    mask13 = data['pmdec'] < pmfield_size
    mask_all = mask & mask1 & mask2 & mask3 & mask4 & mask5 & mask6 & mask7 & mask8 & mask9 & mask10 & mask11 & mask12 & mask13
    return data[mask_all], x[mask_all], y[mask_all]

def make_random_image(data, x, y, gnomonic_width, pmfield_size): 
    '''Makes random field of stars based on real Gaia field. Stellar positions are modeled as 
    poisson process, while the proper motion field is fit by a GMM with 1-4 components  

    Args:
        data (pandas DataFrame): Dataframe containing Gaia data (minimum columns ['ra', 'dec', 'pmra', 'pmdec'])
        x, y (1D float array): gnomonic projections of Gaia data 
        gnomonic_width (float): width of gnomonic field 
        pmfield_size (float): width of proper motion field (assumed to be centered at (0,0))

    Returns:
        rand_x, rand_y, rand_pmra, rand_pmdec (1D float array): random position and proper motion values  
 
    '''
    x_min, x_max = -gnomonic_width, gnomonic_width 
    y_min, y_max = -gnomonic_width, gnomonic_width 
    vra_min, vra_max =  -pmfield_size, pmfield_size
    vdec_min, vdec_max =  -pmfield_size, pmfield_size

    n = 100
    field = np.c_[x, y]
    hist, edges =   np.histogramdd(field, bins=(np.linspace(x_min,x_max,n+1), np.linspace(y_min,y_max,n+1)))

    num_points = int(np.mean(scipy.stats.poisson(np.mean(hist)*n*n).rvs(100)))
    rand_x  = 2*gnomonic_width*scipy.stats.uniform.rvs(0,1,((num_points,1)))+ x_min
    rand_y = 2*gnomonic_width*scipy.stats.uniform.rvs(0,1,((num_points,1))) + y_min

    X = np.array(list(zip(data['pmra'], data['pmdec'])))

    bic = []
    n_components_range = range(1, 5)
    for n_components in n_components_range:
        gmm = GMM(n_components=n_components).fit(X)
        bic.append(gmm.bic(X))

    ncomp = np.argmin(bic)
    gmm = GMM(n_components=n_components_range[ncomp]).fit(X)

    sample = gmm.sample(len(rand_x))
    rand_pmra = (sample[0][:,0])
    rand_pmdec = (sample[0][:,1])

    return rand_x, rand_y, rand_pmra, rand_pmdec

def make_field_image(full_field, gnomonic_width, pmfield_size, n):
    ra_min, ra_max = -gnomonic_width, gnomonic_width
    dec_min, dec_max = -gnomonic_width, gnomonic_width

    vra_min, vra_max = -pmfield_size, pmfield_size
    vdec_min, vdec_max = -pmfield_size, pmfield_size


    field_image, edges = np.histogramdd(full_field,\
                            bins=(np.linspace(ra_min, ra_max, n+1),
                                  np.linspace(dec_min, dec_max, n+1),
                                  np.linspace(vra_min, vra_max, n+1),
                                  np.linspace(vdec_min, vdec_max, n+1) ) )

    return field_image, edges

def find_blobs(out_image, threshold):
    '''Takes 4D image and identifies continuous non-zero regions with at least one pixel 
    with a value > threshold 

    Args:
        out_image (4D array): 4D image data 
        threshold (float): threshold above which to identify regions of interest in the image  

    Returns:
        blobs (list): list of positions and radii (in units of pixels) of non-zero images in region
                      [x1, x2, x3, x4, radius_x1, radius_x2, radius_x3, radius_x4]
                      in wavelet pipeline this corresponds to [ra, dec, pmra, pmdec,
                      radius_ra, radius_dec, radius_pmra, radius_pmdec]
                      
 
    '''
    struct = np.ones((3,3,3,3))
    labels, n = ndimage.measurements.label(out_image, structure=struct)

    significance = []
    blobs = []

    for k in range(1,n+1):
        short = out_image.copy()
        mask = labels == k
        sig = np.max(short[mask])

        if(sig > threshold):
            significance.append(sig)
            short[mask] = 1
            mask = np.invert(mask)
            short[mask] = 0
            a,b,c,d = np.nonzero(short)
            pos = np.array(list(zip(a,b)))

            gmm = GMM(n_components=1,covariance_type='diag').fit(pos)
            X, Y = gmm.means_[0]

            RX, RY = 4*np.sqrt(gmm.covariances_[0])

            pm = np.array(list(zip(c,d)))

            gmm = GMM(n_components=1,covariance_type='diag').fit(pm)
            Z,T = gmm.means_[0]
            RZ, RT = 4*np.sqrt(gmm.covariances_[0])

            blobs.append([X, Y, Z, T, RX, RY, RZ, RT])

    return blobs, significance

def find_clusters(data, x, y, gnomonic_width, pmfield_size, grid_size, blobs): 
    '''Takes positions of non-zero region in image space and selects corresponding stars from Gaia data 

    Args:
        data (pandas DataFrame): Dataframe containing Gaia data (minimum columns ['ra', 'dec', 'pmra', 'pmdec'])
        x, y (1D float array): gnomonic projections of Gaia data 
        gnomonic_width (float): width of gnomonic field 
        pmfield_size (float): width of proper motion field (assumed to be centered at (0,0))
        blobs (list): positions and radii of regions to select stars in units of pixels 

    Returns:
        stars (list): list of pandas DataFrames corresponding to stars selected within the region of each
                      non-zero region in the image 
    '''
    stars = []
    for blob in blobs:
        x_pix = x * grid_size/(2*gnomonic_width)+grid_size/2.
        y_pix = y * grid_size/(2*gnomonic_width)+grid_size/2.
        pmra_pix = data['pmra'] * grid_size/(2*pmfield_size)+grid_size/2.
        pmdec_pix = data['pmdec'] * grid_size/(2*pmfield_size)+grid_size/2.

        cut_idx1 = (x_pix-blob[0])**2/(blob[4])**2+(y_pix-blob[1])**2/(blob[5])**2<1.0
        cut_idx2 = (pmra_pix-blob[2])**2/(blob[6])**2+(pmdec_pix-blob[3])**2/(blob[7])**2<1.0
        stars.append(data[cut_idx1 & cut_idx2])
    return stars

class WaveNet(nn.Module):
    '''Performs wavelet transform on 4D histogram 

    Args:
        n_pos, n_vel (float): dimensions of image to transform 
        J (int):  depth of wavelet transform to perform 
        wavelets (list): list of wavelets to use in transform 
        scales (list): scales of transform to amplify 
        amplifaction (float): amount to amplify each scale in scales 

    Returns:
        output (4D array): transformed image with scales amplified by amplication value
    '''
    def __init__(self, n_pos, n_vel, J=1,\
                 wavelets = ['bior1.1', 'bior2.2', 'bior3.3'],\
                 scales = [1,2,3], amplification=100.): 
        super(WaveNet, self).__init__()

        self.n_pos = n_pos
        self.n_vel = n_vel

        self.nonlinear_op = scales
        self.amplification = amplification 
        self.wavelets = wavelets
        self.wavelet_filters ={}
        self.iwavelet_filters = {}

        for i,w in enumerate(wavelets):

            wavelet = DWTForward(J=J, wave = w)
            setattr(self, 'Wavelet_%d'%i, wavelet)
            self.wavelet_filters[w] = wavelet

            iwavelet = DWTInverse(wave = w)
            setattr(self, 'InvWavelet_%d'%i, iwavelet)
            self.iwavelet_filters[w] = iwavelet

        self.upsample1 = lambda input: F.interpolate(input, size = (n_pos, n_pos))
        self.upsample2 = lambda input: F.interpolate(input, size = (n_vel, n_vel))

    def forward(self, x):
        assert x.shape[0] == x.shape[1] and x.shape[0] == self.n_pos
        assert x.shape[2] == x.shape[3] and x.shape[2] == self.n_vel

        low_wave_outs = []
        high_wave_outs = []

        for w, (wv) in self.wavelet_filters.items():
            #perform wavelet transform on first axis 
            o, hi1 = wv(x)
            o = o.permute(2,3,0,1)
            #perform wavelet transform on second axis 
            o, hi2 = wv(o)
            #perform applification
            for non_lin in self.nonlinear_op:
                    hi1[non_lin] = hi1[non_lin]*self.amplification
                    hi2[non_lin] = hi2[non_lin]*self.amplification

            low_wave_outs.append(o)
            high_wave_outs.append((hi1, hi2))

        output = torch.zeros((self.n_pos, self.n_pos,\
                              self.n_vel, self.n_vel)).to(device)

        for  _o, his, (w,  iwv) in zip(low_wave_outs, high_wave_outs,self.iwavelet_filters.items()):

            o = iwv([_o, his[1]])
            o = o.permute(2,3,0,1)
            o = iwv([o, his[0]])

            output += o

        return output
