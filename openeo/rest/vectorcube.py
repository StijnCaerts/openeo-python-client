import pathlib
import typing
from typing import Union, Optional

from openeo.internal.documentation import openeo_process
from openeo.internal.graph_building import PGNode
from openeo.internal.warnings import legacy_alias
from openeo.metadata import CollectionMetadata
from openeo.rest._datacube import _ProcessGraphAbstraction, UDF
from openeo.rest.mlmodel import MlModel
from openeo.rest.job import BatchJob
from openeo.util import dict_no_none

if typing.TYPE_CHECKING:
    # Imports for type checking only (circular import issue at runtime).
    from openeo import Connection


class VectorCube(_ProcessGraphAbstraction):
    """
    A Vector Cube, or 'Vector Collection' is a data structure containing 'Features':
    https://www.w3.org/TR/sdw-bp/#dfn-feature

    The features in this cube are restricted to have a geometry. Geometries can be points, lines, polygons etcetera.
    A geometry is specified in a 'coordinate reference system'. https://www.w3.org/TR/sdw-bp/#dfn-coordinate-reference-system-(crs)
    """

    def __init__(self, graph: PGNode, connection: 'Connection', metadata: CollectionMetadata = None):
        super().__init__(pgnode=graph, connection=connection)
        # TODO: does VectorCube need CollectionMetadata?
        self.metadata = metadata

    def process(
            self,
            process_id: str,
            arguments: dict = None,
            metadata: Optional[CollectionMetadata] = None,
            namespace: Optional[str] = None,
            **kwargs) -> 'VectorCube':
        """
        Generic helper to create a new DataCube by applying a process.

        :param process_id: process id of the process.
        :param args: argument dictionary for the process.
        :return: new DataCube instance
        """
        pg = self._build_pgnode(process_id=process_id, arguments=arguments, namespace=namespace, **kwargs)
        return VectorCube(graph=pg, connection=self._connection, metadata=metadata or self.metadata)

    @openeo_process
    def run_udf(
        self,
        udf: Union[str, UDF],
        runtime: Optional[str] = None,
        version: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> "VectorCube":
        """
        Run a UDF on the vector cube.

        It is recommended to provide the UDF just as :py:class:`UDF <openeo.rest._datacube.UDF>` instance.
        (the other arguments could be used to override UDF parameters if necessary).

        :param udf: UDF code as a string or :py:class:`UDF <openeo.rest._datacube.UDF>` instance
        :param runtime: UDF runtime
        :param version: UDF version
        :param context: UDF context

        .. warning:: EXPERIMENTAL: not generally supported, API subject to change.

        .. versionadded:: 0.10.0

        .. versionchanged:: 0.16.0
            Added support to pass self-contained :py:class:`UDF <openeo.rest._datacube.UDF>` instance.
        """
        if isinstance(udf, UDF):
            # `UDF` instance is preferred usage pattern, but allow overriding.
            version = version or udf.version
            context = context or udf.context
            runtime = runtime or udf.get_runtime(connection=self.connection)
            udf = udf.code
        else:
            if not runtime:
                raise ValueError("Argument `runtime` must be specified")
        return self.process(
            process_id="run_udf",
            data=self, udf=udf, runtime=runtime,
            arguments=dict_no_none({"version": version, "context": context}),
        )

    @openeo_process
    def save_result(self, format: str = "GeoJson", options: dict = None):
        return self.process(
            process_id="save_result",
            arguments={
                "data": self,
                "format": format,
                "options": options or {}
            }
        )

    def execute(self) -> dict:
        """Executes the process graph of the imagery."""
        return self._connection.execute(self.flat_graph())

    def download(self, outputfile: str, format: str = "GeoJSON", options: dict = None):
        # TODO: only add save_result, when not already present (see DataCube.download)
        cube = self.save_result(format=format, options=options)
        return self._connection.download(cube.flat_graph(), outputfile)

    def execute_batch(
            self,
            outputfile: Union[str, pathlib.Path] = None, out_format: str = None,
            print=print, max_poll_interval=60, connection_retry_interval=30,
            job_options=None, **format_options) -> BatchJob:
        """
        Evaluate the process graph by creating a batch job, and retrieving the results when it is finished.
        This method is mostly recommended if the batch job is expected to run in a reasonable amount of time.

        For very long running jobs, you probably do not want to keep the client running.

        :param job_options:
        :param outputfile: The path of a file to which a result can be written
        :param out_format: (optional) Format of the job result.
        :param format_options: String Parameters for the job result format

        """
        job = self.create_job(out_format, job_options=job_options, **format_options)
        return job.run_synchronous(
            # TODO #135 support multi file result sets too
            outputfile=outputfile,
            print=print, max_poll_interval=max_poll_interval, connection_retry_interval=connection_retry_interval
        )

    def create_job(
        self,
        out_format: Optional[str] = None,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        plan: Optional[str] = None,
        budget: Optional[float] = None,
        job_options: Optional[dict] = None,
        **format_options,
    ) -> BatchJob:
        """
        Sends a job to the backend and returns a ClientJob instance.

        :param out_format: String Format of the job result.
        :param title: job title
        :param description: job description
        :param plan: billing plan
        :param budget: maximum cost the request is allowed to produce
        :param job_options: A dictionary containing (custom) job options
        :param format_options: String Parameters for the job result format
        :return: Created job.
        """
        # TODO: avoid using all kwargs as format_options
        # TODO: centralize `create_job` for `DataCube`, `VectorCube`, `MlModel`, ...
        cube = self
        if out_format:
            # add `save_result` node
            cube = cube.save_result(format=out_format, options=format_options)
        return self._connection.create_job(
            process_graph=cube.flat_graph(),
            title=title,
            description=description,
            plan=plan,
            budget=budget,
            additional=job_options,
        )

    send_job = legacy_alias(create_job, name="send_job", since="0.10.0")

    @openeo_process
    def fit_class_random_forest(
        self,
        # TODO #279 #293: target type should be `VectorCube` (with adapters for GeoJSON FeatureCollection, GeoPandas, ...)
        target: dict,
        # TODO #293 max_variables officially has no default
        max_variables: Optional[int] = None,
        num_trees: int = 100,
        seed: Optional[int] = None,
    ) -> MlModel:
        """
        Executes the fit of a random forest classification based on the user input of target and predictors.
        The Random Forest classification model is based on the approach by Breiman (2001).

        .. warning:: EXPERIMENTAL: not generally supported, API subject to change.

        :param target: The training sites for the classification model as a vector data cube. This is associated with the target
            variable for the Random Forest model. The geometry has to be associated with a value to predict (e.g. fractional
            forest canopy cover).
        :param max_variables: Specifies how many split variables will be used at a node. Default value is `null`, which corresponds to the
            number of predictors divided by 3.
        :param num_trees: The number of trees build within the Random Forest classification.
        :param seed: A randomization seed to use for the random sampling in training.

        .. versionadded:: 0.16.0
            Originally added in version 0.10.0 as :py:class:`DataCube <openeo.rest.datacube.DataCube>` method,
            but moved to :py:class:`VectorCube` in version 0.16.0.
        """
        pgnode = PGNode(
            process_id="fit_class_random_forest",
            arguments=dict_no_none(
                predictors=self,
                # TODO #279 strictly per-spec, target should be a `vector-cube`, but due to lack of proper support we are limited to inline GeoJSON for now
                target=target,
                max_variables=max_variables,
                num_trees=num_trees,
                seed=seed,
            ),
        )
        model = MlModel(graph=pgnode, connection=self._connection)
        return model

    @openeo_process
    def fit_regr_random_forest(
        self,
        # TODO #279 #293: target type should be `VectorCube` (with adapters for GeoJSON FeatureCollection, GeoPandas, ...)
        target: dict,
        # TODO #293 max_variables officially has no default
        max_variables: Optional[int] = None,
        num_trees: int = 100,
        seed: Optional[int] = None,
    ) -> MlModel:
        """
        Executes the fit of a random forest regression based on training data.
        The Random Forest regression model is based on the approach by Breiman (2001).

        .. warning:: EXPERIMENTAL: not generally supported, API subject to change.

        :param target: The training sites for the regression model as a vector data cube.
            This is associated with the target variable for the Random Forest model.
            The geometry has to associated with a value to predict (e.g. fractional forest canopy cover).
        :param max_variables: Specifies how many split variables will be used at a node. Default value is `null`, which corresponds to the
            number of predictors divided by 3.
        :param num_trees: The number of trees build within the Random Forest classification.
        :param seed: A randomization seed to use for the random sampling in training.

        .. versionadded:: 0.16.0
            Originally added in version 0.10.0 as :py:class:`DataCube <openeo.rest.datacube.DataCube>` method,
            but moved to :py:class:`VectorCube` in version 0.16.0.
        """
        # TODO #279 #293: `fit_class_random_forest` should be defined on VectorCube instead of DataCube
        pgnode = PGNode(
            process_id="fit_regr_random_forest",
            arguments=dict_no_none(
                predictors=self,
                # TODO #279 strictly per-spec, target should be a `vector-cube`, but due to lack of proper support we are limited to inline GeoJSON for now
                target=target,
                max_variables=max_variables,
                num_trees=num_trees,
                seed=seed,
            ),
        )
        model = MlModel(graph=pgnode, connection=self._connection)
        return model
