class User(object):
    def __init__(self, **kwargs):
        if "user" in kwargs:
            user = kwargs['user']
            self.user_id = user.id
            self.name = user.first_name
        else:
            if not ("user_id" in kwargs and "name" in kwargs):
                raise ValueError()
            self.user_id = kwargs['user_id']
            self.name = kwargs['name']

    def __hash__(self):
        return hash(self.user_id)

    def __eq__(self, other):
        return self.user_id == other.user_id

    def __lt__(self, other):
        return self.name < other.name
