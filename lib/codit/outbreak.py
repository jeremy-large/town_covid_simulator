import pandas as pd
import logging


from codit.population.covid import PersonCovid
from codit.population.population import FixedNetworkPopulation
from codit.outbreakvisualiser import VisualizerComponent


class Outbreak:
    def __init__(self, society, diseases, pop_size=0, seed_size=0, n_days=0,
                 population=None,
                 population_type=None,
                 person_type=None,
                 show_heatmap=False):

        self.pop = self.prepare_population(pop_size, population, population_type, society, person_type)
        society.clear_queues()
        self.pop.seed_infections(seed_size, diseases)

        self.initialize_timers(n_days, society.episodes_per_day)
        self.group_size = society.encounter_size

        self.society = society
        self.diseases = diseases
        # Add a switch of heatmap video
        self.set_recorder(show_heatmap=show_heatmap)


    def prepare_population(self, pop_size, population, population_type, society, person_type):
        if population:
            assert pop_size in (0, len(population.people)), "provide a population of the correct size"
            logging.warning("Using a pre-existing population - does it have the right network structure?")
            if person_type is not None:
                assert {person_type} == set(type(p) for p in population.people), \
                    "The people in this population are of the wrong type"
            population.reset_people(society)
            self.pop = population
            return population

        population_type = population_type or FixedNetworkPopulation
        person_type = person_type or PersonCovid
        return population_type(pop_size, society, person_type=person_type)

    def set_recorder(self, recorder=None, show_heatmap=False):
        self.recorder = recorder or OutbreakRecorder(self, show_heatmap)

    def initialize_timers(self, n_days, enc_per_day):
        self.n_days = n_days
        self.n_periods = n_days * enc_per_day
        self.time_increment = 1 / enc_per_day

        self.time = 0
        self.step_num = 0

    def simulate(self):
        for t in range(self.n_periods):
            self.update_time()
            self.society.manage_outbreak(self.pop)
            self.pop.attack_in_groupings(self.group_size)
            self.record_state()

        self.recorder.realized_r0 = self.pop.realized_r0()
        self.recorder.society_config = self.society.cfg

        if type(self.diseases) is set:
            self.recorder.disease_config = [d.cfg for d in self.diseases]
        else:
            self.recorder.disease_config = self.diseases.cfg

        return self.recorder

    def update_time(self):
        self.pop.update_time()
        self.time += self.time_increment
        self.step_num += 1

    def record_state(self):
        self.recorder.record_step(self)

    def plot(self, **kwargs):
        self.recorder.plot(**kwargs)


class OutbreakRecorder:
    def __init__(self, o, show_heatmap=False):
        self.realized_r0 = None
        self.components = [MainComponent()]
        if show_heatmap:
            self.components.append(VisualizerComponent(False, o))
        self.main_component = self.components[0]

    def add_component(self, component):
        self.components.append(component)

    def record_step(self, o):
        for component in self.components:
            component.update(o)

    def plot(self, **kwargs):
        df = self.get_dataframe()
        ax = (df.drop(columns=['ever infected']) * 100).plot(grid=True, **kwargs)
        ax.set_ylabel("percent of the population")
        logging.info(f" Realized R0 of early infections is {self.realized_r0:2.2f}")
        logging.info(f" {self.main_component.story[-1][1] * 100:2.1f} percent of the proportion was infected during the epidemic")

    def get_dataframe(self):
        df = pd.DataFrame(self.main_component.story)
        df.columns = ['days of epidemic', 'ever infected', 'infectious',
                      'tested daily', 'waiting for test results', 'isolating']  # , 'daily_detected_']
        df = df.set_index('days of epidemic')
        return df


class MainComponent:
    def __init__(self):
        self.story = []

    def update(self, o):
        N = len(o.pop.people)
        # pot_haz = sum([covid_hazard(person.age) for person in o.pop.people])
        # tot_haz = sum([covid_hazard(person.age) for person in o.pop.infected()])

        all_completed_tests = [t for q in o.society.queues for t in q.completed_tests]
        step = [o.time,
                o.pop.count_infected() / N,
                o.pop.count_infectious() / N,
                len(all_completed_tests) / N / o.time_increment,
                sum(len([t for t in q.tests if t.swab_taken]) for q in o.society.queues) / N,
                sum(p.isolating for p in o.pop.people) / N,
                # len([t for t in all_completed_tests if t.positive]) / N / o.time_increment,
                # tot_haz/pot_haz,
                ]
        self.story.append(step)

        # wards = {p.home.ward for p in o.pop.people}
        # step_wards = [wards, [o.pop.count_infected(d, lamda)]]

        if o.step_num % (50 * o.society.episodes_per_day) == 1 or (o.step_num == o.n_periods):
            logging.info(f"Day {int(step[0])}, prop infected is {step[1]:2.2f}, "
                         f"prop infectious is {step[2]:2.4f}")


class VariantComponent:
    def __init__(self):
        self.story = []

    def update(self, o):
        variants = list({d for p in o.pop.people for d in p.covid_experiences})
        self.story.append([o.time,
                           variants,
                           [o.pop.count_infected(d) for d in variants],
                           [o.pop.count_infectious(d) for d in variants]])
