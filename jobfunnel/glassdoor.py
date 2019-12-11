## scrapes data off glassdoor.ca and pickles it

import logging
import requests
import bs4
import re
import os
from threading import Thread
from math import ceil

from .jobfunnel import JobFunnel, MASTERLIST_HEADER
from .tools.tools import filter_non_printables
from .tools.tools import post_date_from_relative_post_age
from .tools.filters import id_filter


class GlassDoor(JobFunnel):

    def __init__(self, args):
        super().__init__(args)
        self.provider = 'glassdoor'
        self.max_results_per_page = 30
        self.headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;'
                      'q=0.9,image/webp,*/*;q=0.8',
            'accept-encoding': 'gzip, deflate, sdch, br',
            'accept-language': 'en-GB,en-US;q=0.8,en;q=0.6',
            'referer': 'https://www.glassdoor.{0}/'.format(
                self.search_terms['region']['domain']),
            'upgrade-insecure-requests': '1',
            'user-agent': self.user_agent,
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive'
        }
        self.location_headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,'
                      'image/webp,*/*;q=0.01',
            'accept-encoding': 'gzip, deflate, sdch, br',
            'accept-language': 'en-GB,en-US;q=0.8,en;q=0.6',
            'referer': 'https://www.glassdoor.{0}/'.format(
                self.search_terms['region']['domain']),
            'upgrade-insecure-requests': '1',
            'user-agent': self.user_agent,
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive'
        }

    def convert_glassdoor_radius(self, radius):
        """function that quantizes the user input radius to a valid
           radius value: 10, 20, 30, 50 and 100 kilometers"""

        if radius < 10:
            radius = 0
        elif 10 <= radius < 20:
            radius = 10
        elif 20 <= radius < 30:
            radius = 20
        elif 30 <= radius < 50:
            radius = 30
        elif 50 <= radius < 100:
            radius = 50
        elif radius >= 100:
            radius = 100

        glassdoor_radius = {
            0: 0,
            10: 6,
            20: 12,
            30: 19,
            50: 31,
            100: 62
        }

        return glassdoor_radius[radius]

    def search_glassdoor_page_for_job_soups(self, data, page,
                                            page_url, list_of_job_soups):
        """function that scrapes the glassdoor page for a list of job soups"""
        logging.info(
            'getting glassdoor page {0} : {1}'.format(page, page_url))
        jobs = bs4.BeautifulSoup(
            requests.post(page_url, headers=self.headers, data=data).text,
            self.bs4_parser).find_all('li', attrs={'class', 'jl'})
        list_of_job_soups.extend(jobs)

    def search_glassdoor_joblink_for_blurb(self, job):
        """function that scrapes the glassdoor job link for the blurb"""
        search = job['link']
        logging.info(
            'getting glassdoor search: {}'.format(search))
        request_HTML = requests.post(search, headers=self.location_headers)
        job_link_soup = bs4.BeautifulSoup(request_HTML.text,
                                          self.bs4_parser)

        try:
            job['blurb'] = job_link_soup.find(
                id='JobDescriptionContainer').text.strip()
        except AttributeError:
            job['blurb'] = ''

        filter_non_printables(job)

    def scrape(self):
        """function that scrapes job posting from glassdoor and pickles it"""
        ## scrape a page of monster results to a pickle
        logging.info(
            'jobfunnel glassdoor to pickle running @' + self.date_string)

        # initialize and store date quantifiers as regex objects in list.
        date_regex = [re.compile(r'(\d+)(?:[ +]{1,3})?(?:hour|hr)'),
                      re.compile(r'(\d+)(?:[ +]{1,3})?(?:day|d)'),
                      re.compile(r'(\d+)(?:[ +]{1,3})?month'),
                      re.compile(r'(\d+)(?:[ +]{1,3})?year'),
                      re.compile(r'[tT]oday|[jJ]ust [pP]osted'),
                      re.compile(r'[yY]esterday')]

        # form the query string
        query = '-'.join(self.search_terms['keywords'])

        data = {'term': self.search_terms['region']['city'],
                'maxLocationsToReturn': 10}

        location_url = \
            'https://www.glassdoor.co.in/findPopularLocationAjax.htm?'

        # get the location id for search location
        location_response = requests.post(location_url,
                                          headers=self.location_headers,
                                          data=data).json()
        place_id = location_response[0]['locationId']
        job_listing_url = 'https://www.glassdoor.{0}/Job/jobs.htm'.format(
            self.search_terms['region']['domain'])

        # form data to get job results
        data = {
            'clickSource': 'searchBtn',
            'sc.keyword': query,
            'locT': 'C',
            'locId': place_id,
            'jobType': '',
            'radius': self.convert_glassdoor_radius(
                self.search_terms['region']['radius'])
        }

        # get the HTML data, initialize bs4 with lxml
        request_HTML = requests.post(
            job_listing_url, headers=self.headers, data=data)
        soup_base = bs4.BeautifulSoup(request_HTML.text, self.bs4_parser)

        # scrape total number of results, and calculate the # pages needed
        # Now with less regex!
        num_results = soup_base.find(
            'p', attrs={'class', 'jobsCount'}).text.strip()
        num_results = int(re.findall(r'(\d+)',
                                     num_results.replace(',', ''))[0])

        logging.info('Found {} glassdoor results for query={}'.format(
            num_results, query))

        # scrape soups for all the pages containing jobs it found
        list_of_job_soups = []
        pages = int(ceil(num_results / self.max_results_per_page))

        # search the pages to extract the list of job soups
        threads = []
        for page in range(1, pages):
            if page == 1:
                page_url = request_HTML.url
            else:
                page_url = 'https://www.glassdoor.{0}{1}'.format(
                    self.search_terms['region']['domain'],
                    soup_base.find('li',
                                   attrs={'class',
                                          'next'}).find('a').get('href'))
                page_url = re.sub(r'_IP\d+\.', "_IP" + str(page) + ".",
                                  page_url)
            process = Thread(target=self.search_glassdoor_page_for_job_soups,
                             args=[data, page, page_url, list_of_job_soups])
            process.start()
            threads.append(process)

        for process in threads:
            process.join()

        # make a dict of job postings from the listing briefs
        for s in list_of_job_soups:
            # init dict to store scraped data
            job = dict([(k, '') for k in MASTERLIST_HEADER])

            # scrape the post data
            job['status'] = 'new'
            try:
                # jobs should at minimum have a title, company and location
                job['title'] = s.find('div', attrs={'class', 'jobContainer'}).\
                    find('a', attrs={'class', 'jobLink jobInfoItem jobTitle'},
                         recursive=False).text.strip()
                job['company'] = s.find('div', attrs={'class', 'jobInfoItem '
                                                      'jobEmpolyerName'}).\
                    text.strip()
                job['location'] = s.get('data-job-loc')
            except AttributeError:
                continue

            # no blurb is available in glassdoor job soups
            job['blurb'] = ''

            try:
                job['date'] = s.find('div', attrs={'class', 'jobLabels'}).find(
                    'span', attrs={'class', 'jobLabel nowrap'}).text.strip()
            except AttributeError:
                job['date'] = ''

            try:
                job['id'] = s.get('data-id')
                job['link'] = 'https://www.glassdoor.{0}{1}'.format(
                    self.search_terms['region']['domain'],
                    s.find('div', attrs={'class', 'logoWrap'}).find('a').get(
                        'href'))
            except (AttributeError, IndexError):
                job['id'] = ''
                job['link'] = ''

            job['provider'] = self.provider

            post_date_from_relative_post_age(job, date_regex)

            # key by id
            self.scrape_data[str(job['id'])] = job

        # Pop duplicate job ids already in master list
        if os.path.exists(self.master_list_path):
            id_filter(self.scrape_data,
                      super().read_csv(self.master_list_path), self.provider)
        # search the job link to extract the blurb
        scrape_data_list = [i for i in self.scrape_data.values()]
        threads = []
        for job in scrape_data_list:
            if job['provider'] == self.provider:
                process = Thread(
                    target=self.search_glassdoor_joblink_for_blurb,
                    args=[job])
                process.start()
                threads.append(process)

        for process in threads:
            process.join()
