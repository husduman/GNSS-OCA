# goca/archive_urls.py

from datetime import date


class ArchiveURL:

    def __init__(self, template):
        self.template = template

    def date(self, dt):

        gps_epoch = date(1980, 1, 6)

        gps_days = (dt - gps_epoch).days
        gps_week = gps_days // 7

        url = self.template
        url = url.replace("WWWW", f"{gps_week:04d}")
        url = url.replace("YYYY", f"{dt.year}")

        return url

    def __str__(self):
        return self.template


ARCHIVE_URLS = {

    "CDDIS": ArchiveURL(
        "https://cddis.nasa.gov/archive/gnss/products/WWWW/"
    ),

    "IGN": ArchiveURL(
        "ftp://igs.ign.fr/pub/igs/products/WWWW/"
    ),

    "WHU": ArchiveURL(
        "ftp://igs.gnsswhu.cn/pub/gps/products/WWWW/"
    ),

    "WHUmgex": ArchiveURL(
        "ftp://igs.gnsswhu.cn/pub/gnss/products/mgex/WWWW/"
    ),

    "HUS": ArchiveURL(
        "ftp://ggda.ac.cn/pub/mgex/products/YYYY/"
    ),

    "WCCpride": ArchiveURL(
        "ftps://bdspride.com/wcc/WWWW/"
    ),

    "WUMpride": ArchiveURL(
        "ftps://bdspride.com/wum/WWWW/"
    ),
}