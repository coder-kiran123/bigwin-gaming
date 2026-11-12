from .milkyway import MilkyWayAPI

# Orion Stars runs the identical ASP.NET WebForms platform as Milky Way.
# Reuse the full implementation — only the default base URL differs.

class OrionStarsAPI(MilkyWayAPI):
    def __init__(self, username, password, token='', base_url='https://orionstars.vip:8781'):
        super().__init__(username, password, token=token, base_url=base_url)

    def test_connection(self):
        ok, msg = super().test_connection()
        if ok:
            return True, msg.replace('Milky Way', 'Orion Stars')
        return False, msg
