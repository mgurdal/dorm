from . import models
from datetime import datetime
#from pprint import pprint as print
# from .conf import NODES
from itertools import chain
import docker
def progress(label, current, total, unit="bytes"):
    per = "#" * int(current / int(total) * 50)
    if current == total - 1:
        print("\r {}: [{:50}] {:,}/{:,}".format(label, "#"*50, current+1, total), end="")
        return
    print("\r {}: [{:50}] {:,}/{:,}".format(label, per, current, total), end="")
    # print("\r {}: [{:50}] {:,}/{:,} {}".format(label, per, current, total, unit), end="")

class Node(object):
    """
    Node
        'binds to' drivers
        'connects to' databases
        'generates' models
    """

    def __init__(self, _id, ip, name='dorm', port=1307, type_='postgres', replica=False):
        self._id = _id
        self.name = name
        self.type_ = type_
        self.replica = replica
        self.ip = ip
        self.port = port

        self._models = {}
        self._model_store = []
        if type_ == 'sqlite':
            from .drivers import Sqlite
            self.driver = Sqlite(dbname="sqlite", user="docker", host=ip, password="docker")

        elif type_ == 'postgres':
            from .drivers import Postgres
            self.driver = Postgres(dbname=name, host=ip, user="docker", password="docker")

    def collect_models(self):
        assert hasattr(self, 'driver'), 'Node does not have a driver'
        model_structures = self.driver.discover()
        ms = []
        for model_s in model_structures:
            fs = [models.Field.from_dict(x, registery=self._models) for x in model_s['columns']]
            mod = models.model_meta(model_s['table_name'].title(), (models.Model,), {f.name:f for f in fs})
            # handle relation in here via fields referance info
            # print(model_s['table_name'])
            mod._node = self
            mod._shape = model_s
            ms.append(mod)
            self._models[mod.__name__] = mod
            self._model_store.append(model_s)

        for model_name, model in self._models.items():
            for name, field in model.__fields__.items():
                if type(field) is models.ForeignKey and (len(field.to_table.__fields__) != len(self._models[field.to_table.__name__].__fields__)):
                    self._models[model_name].__fields__.update({name:models.ForeignKey(self._models[field.to_table.__name__])})
        return ms

    def add_model(self, *models):
        assert hasattr(self, 'driver'), 'Node does not have a driver'
        for model in models:
            self.driver.create_table(model)

    def save_model(self, *model_batch):
        assert hasattr(self, 'driver'), 'Node does not have a driver'

        base_query = 'insert into {tablename}({columns}) values{batch};'
        value_batch = []
        for model in model_batch:
            columns = []
            values = []

            for field_name, field_model in model.__fields__.items():
                if hasattr(model, field_name) and not isinstance(getattr(model, field_name), models.Field):
                    values.append(field_model._format(getattr(model, field_name)))
                    columns.append(field_name)

            value_batch.append(",".join(values))
            # print(values)
        sql = base_query.format(
            tablename=model.__class__.__name__,
            columns=', '.join(columns),
            batch=",".join(map(lambda x:"({})".format(x), value_batch))
        )
        print(sql)
        cursor = self.driver.execute(sql)


        self.driver.commit()

    def save_node(self, driver):
        assert hasattr(self, 'driver'), 'Node does not have a driver'

        base_query = 'insert into {tablename}({columns}) values({batch});'
        value_batch = []
        values = []
        columns = []
        for field_name, field_model in self.__fields__.items():
            if hasattr(self, field_name) and not isinstance(getattr(self, field_name), models.Field):
                values.append(field_model._format(getattr(self, field_name)))
                columns.append(field_name)

        sql = base_query.format(
            tablename=self.__class__.__name__,
            columns=', '.join(columns),
            batch=", ".join(values)
        )
        cursor = driver.execute(sql)
        # validate that its really added to database
        assert cursor, "Could not add to database"
        driver.commit()

    def connect(self):
        # try to connect to the database inside the docker container
        pass

class ModelQuery(dict):
    """
        q1 ^ q2
        q.select('f')...
        takes models and filters them accordingly
        act like models when chaining queries
        acts like sets when doing math operations
        also supports model queries with class methods
    """

    #_nodes = []
    def __init__(self):
        self._models = {}
        self._queries = []

    def select(cls, *args, **kwargs):
        """ Lazy select
            Cool loading
            Async
        """
        cls._queries = [model.select(*args, **kwargs) for _, model in cls._models.items()]
        return cls

    def where(cls, **kwargs):
        cls._queries = [query.where(**kwargs) for query in cls._queries]
        return cls

    def all(self):
        return chain(*[sq.all() for sq in self._queries])

    def df(self):
        import pandas
        return pandas.DataFrame.from_records(self.all())

class DORM(object):
    """
        n1 = Node(ip="0.0.0.0", port=0, name='mysqlite', user='sky', password='123', type_='sqlite')
        sq1 = Sqlite(name='test-2.3.sqlite')
        n1.bind(sq1)

        d = DORM()
        d.discover()
        d.find("User").select('name').all()
    """

    dockerclient = docker.from_env()
    _node_store = {}

    def cast(self, iterable):
        x = []
        for i, data in enumerate(iterable):
            progress("Total", i+1, i+1, "items")
            x.append(data)
        print()
        return x

    def discover(self):
        self._node_store = {}
        dorm_net = self.dockerclient.networks.get("dorm_net").containers
        amount = len(dorm_net)
        for i, x in enumerate(dorm_net):
            host = x.attrs['NetworkSettings']['Networks']['dorm_net']['IPAddress'],
            container_id = hash(x.short_id)
            if container_id in self._node_store:
                print("Already exists", container_id)
                continue
            new_node = Node(_id=container_id, ip=host[0], name="dorm", type_="postgres", replica=False) # rep test
            new_node.collect_models()
            self._node_store[container_id] = new_node
            progress("Node [{}]".format(host[0]), i, amount, "")
        print()

    def add_node(self, n):
        # n.save_node(self._ext_table)
        #n.collect_models()
        self._node_store[n._id] = n

    @property
    def first(self):
        return list(self._node_store.values())[0]

    @property
    def models(self):
        return list(d._node_store.values())[0]

    @property
    def models(self):
        for name, node in self._node_store.items():
            for model in node._model_store:
                print("\t", model['table_name'])

    def collect_models(self):
        for key, node in self._node_store.items():
            node.collect_models()

    # @classmethod
    def find(self, target_model):
        """
        # does it fight with other nodes
        # d+oes it fight with other models
        # filter replications
        # if I say get name dont get name
            column from all models

        # I dont care about nodes just gimme the data!
        # select models(tables) and Q on 'em

        d.find('model').select('field')
        """
        # can be changed with SelectQuery
        mq = ModelQuery()
        count = 0
        for n_name, node in self._node_store.items():
            if not node.replica:
                for m_name, model in node._models.items():
                    if m_name == target_model:
                        count += 1
                        progress("Node", count, count, "")
                        # might need to change to id or auto assigned name
                        mq._models[m_name] = model
        print()
        # reduce node store - done
        # find model - done
        # execute q - done
        # collect & merge - done
        return mq # node collection


    def add(self, m, to_node=None):
        # where to put
        # find nodes that contains related tables
        # health_check
        # size check
        # create table
        for n_name, node in self._node_store.items():
            print("Adding to", node.ip)
            node.add_model(m)

    def save(self, m, to_node=None):
        # where to put
        # find nodes that contains related tables
        # health_check
        # size check
        # create table
        for n_name, node in self._node_store.items():
            if m.__class__.__name__ in node._models:
                print("Saving to", node.ip)
                node.save_model(m)
            else:
                print("Not found in", node.ip)

    def rollback_all(self):
        for _, n in self._node_store.items():
            n.driver.rollback()

    def health_check(self):
        pass

    def replication_check(self):
        pass

    def clone_node(self, from_node, to_node):
        pass

    def clone_model(self, model, from_node, to_node):
        pass

    def create_node(self, replica=False):
        # spin a docker container
        container = self.dockerclient.containers.run('dorm_postgres', network_mode="dorm_net", detach=True)
        # print(container.status)
        import time
        new_node = None
        for cont in self.dockerclient.networks.get('dorm_net').containers:
            if cont.short_id == container.short_id:
                _id = hash(cont.short_id)
                ip = cont.attrs['NetworkSettings']['Networks']['dorm_net']['IPAddress']
                while 1:
                    try:
                        Node(_id=_id, ip=ip, name="dorm", type_="postgres", replica=replica)
                        break
                    except Exception as e:
                        time.sleep(1)
                new_node = Node(_id=_id, ip=ip, name="dorm", type_="postgres", replica=replica)

                if new_node:
                    new_node.collect_models()
                    self.add_node(new_node)
                    return new_node
        else:
            raise Exception("Could not create!")

if __name__ == '__main__':
    import sys, os

    d = DORM()
